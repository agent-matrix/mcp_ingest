from __future__ import annotations

"""
Repo-wide harvester/orchestrator.

What it does
------------
Given a *source* (local dir | git URL | zip URL), it:
  1) prepares a local working copy (see utils.fetch.prepare_source)
  2) finds candidate subfolders that likely contain MCP servers
  3) runs a detector chain per candidate (fastmcp → node_mcp → langchain → raw_mcp)
  4) emits a *per-server* manifest.json + index.json via sdk.describe(...)
  5) writes a *repo-level* index.json that lists all discovered manifests
  6) optionally publishes artifacts (publishers.static_index) and/or registers to MatrixHub

Design notes
------------
- Root folder is now considered a candidate **if** it looks like a server dir.
- Rich DEBUG logs are emitted for discovery and detector decisions.
- If detectors return no usable signal, we **still emit a minimal manifest**
  for directories that match our server heuristics (so local examples work
  without deep framework cues).
- We always write a repo-level index.json (even if empty) to aid debugging.

Compatibility: MatrixHub /catalog/install (via sdk.autoinstall)
"""

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..detect.base import DetectReport
from ..detect.fastmcp import detect_path as detect_fastmcp
from ..detect.langchain import detect_path as detect_langchain
from ..detect.raw_mcp import detect_path as detect_raw_mcp
from ..emit.enrich import enrich_manifest
from ..emit.index import write_index
from ..sdk import autoinstall as sdk_autoinstall
from ..sdk import describe as sdk_describe
from ..utils.fetch import LocalSource, prepare_source

# Optional publisher; imported lazily when used
try:  # pragma: no cover (optional dep path at runtime)
    from ..publishers.static_index import publish as publish_static
except Exception:  # pragma: no cover
    publish_static = None  # type: ignore

__all__ = ["HarvestResult", "harvest_repo"]

log = logging.getLogger(__name__)


# ----------------------------
# Public API
# ----------------------------


@dataclass
class HarvestResult:
    manifests: list[Path]  # all created manifests (absolute paths)
    index_path: Path  # repo-level index.json (absolute path)
    errors: list[str]
    summary: dict[str, object]  # counts, frameworks, transports, detectors, etc.


def harvest_repo(
    source: str,
    *,
    out_dir: str | Path,
    publish: str | None = None,
    register: bool = False,
    matrixhub_url: str | None = None,
) -> HarvestResult:
    """Harvest a repo for MCP servers and emit manifests/index.

    Parameters
    ----------
    source : str
        dir path | git URL (optionally @ref) | zip URL
    out_dir : Path-like
        Where to write per-server outputs and the repo-level index.json
    publish : str | None
        Destination for publishing (e.g., "s3://bucket/prefix" or "ghpages://org/repo/docs/")
    register : bool
        If True, post each manifest into MatrixHub via /catalog/install
    matrixhub_url : str | None
        Required when register=True; MatrixHub base URL
    """

    log.info(
        "harvest_repo: source=%s out_dir=%s register=%s publish=%s",
        source,
        out_dir,
        register,
        bool(publish),
    )

    manifests: list[Path] = []
    errors: list[str] = []
    by_detector: dict[str, int] = {"fastmcp": 0, "node": 0, "langchain": 0, "raw": 0}
    transports: dict[str, int] = {"sse": 0, "messages": 0, "unknown": 0}

    # 1) Prepare local working copy
    try:
        local: LocalSource = prepare_source(source)
        log.debug(
            "prepared source: kind=%s path=%s repo=%s sha=%s",
            local.kind,
            local.path,
            local.repo_name,
            local.sha,
        )
    except Exception as e:  # pragma: no cover - network/OS dependent
        log.error("prepare_source failed for %s: %s", source, e)
        raise RuntimeError(f"prepare_source failed for {source}: {e}") from e

    try:
        # 2) Find candidate subfolders (include root if it looks like a server)
        candidates = list(_iter_candidate_dirs(local.path))
        if not candidates:
            msg = f"No server-like candidates found under {local.path}"
            log.warning(msg)
            errors.append(msg)

        # 3) Prepare output root
        out_root = Path(out_dir).expanduser().resolve()
        out_root.mkdir(parents=True, exist_ok=True)
        log.debug("output root: %s", out_root)

        # 4) Process candidates
        for cdir in candidates:
            log.info("candidate: %s", cdir)
            try:
                report, detector_tag = _run_detectors_in_order(cdir)
                log.debug(
                    "detector result: dir=%s detector=%s conf=%.2f tools=%s url=%s",
                    cdir,
                    detector_tag,
                    (report.confidence or 0.0) if hasattr(report, "confidence") else 0.0,
                    len(report.tools or []) if hasattr(report, "tools") and report.tools else 0,
                    getattr(report, "server_url", ""),
                )

                use_minimal = not _has_signal(report)
                if use_minimal:
                    log.warning("no detector signal for %s — emitting minimal manifest", cdir)
                else:
                    by_detector[detector_tag] = by_detector.get(detector_tag, 0) + 1

                # Name & URL synthesis
                name = (
                    report.suggest_name(default=cdir.name)
                    if hasattr(report, "suggest_name")
                    else cdir.name
                ) or cdir.name
                url = getattr(report, "server_url", None) or _default_url()
                ttag = _transport_tag(url)
                transports[ttag] = transports.get(ttag, 0) + 1

                # Tools list for describe() (keep simple: names/ids)
                tools = []
                if hasattr(report, "tools") and report.tools:
                    tools = [
                        t.get("name") or t.get("id") for t in report.tools if isinstance(t, dict)
                    ]
                    tools = [t for t in tools if t]

                # Resources passthrough (best-effort); add a hint file if we emit minimal
                resources = list(getattr(report, "resources", []) or [])
                if use_minimal:
                    hint = _first_existing(
                        cdir / "server.py", cdir / "app.py", cdir / "main.py", cdir / "package.json"
                    )
                    if hint is not None:
                        resources.append({"uri": f"file://{hint}", "name": hint.name})

                # Per-server output dir: make a stable slug
                rel_slug = _slug_from_repo_and_path(local, cdir)
                srv_out = out_root / rel_slug
                srv_out.mkdir(parents=True, exist_ok=True)

                # 5) Emit manifest + index via SDK
                dres = sdk_describe(
                    name=name,
                    url=url,
                    tools=tools or None,
                    resources=resources or None,
                    description=(
                        report.summarize_description()
                        if hasattr(report, "summarize_description")
                        else ""
                    )
                    or "",
                    version="0.1.0",
                    out_dir=srv_out,
                )
                mpath = Path(dres["manifest_path"]).resolve()
                manifests.append(mpath)

                # --- NEW: compute enrichment context ---
                git_origin = None
                homepage = None
                git_ref = local.sha or None

                if local.kind == "git":
                    # normalize to https://github.com/.../.git if possible
                    git_origin = local.origin
                    if (
                        git_origin
                        and not git_origin.endswith(".git")
                        and git_origin.startswith("https://github.com/")
                    ):
                        git_origin = git_origin + ".git"
                    homepage = (
                        git_origin[:-4]
                        if git_origin and git_origin.endswith(".git")
                        else local.origin
                    )
                elif local.kind == "zip":
                    # If origin is a GitHub codeload zip URL, homepage may be the repo page (best-effort)
                    homepage = local.origin  # harmless; enrich() will keep it or empty string

                # Find a server.py to link in resources (optional best-effort)
                server_relpath = None
                server_file = None
                candidate_server = cdir / "server.py"
                if candidate_server.exists():
                    server_file = candidate_server
                else:
                    # small search inside candidate dir
                    for py in cdir.rglob("server.py"):
                        server_file = py
                        break

                if server_file is not None:
                    try:
                        server_relpath = str(
                            server_file.resolve().relative_to(local.path.resolve()).as_posix()
                        )
                    except Exception:
                        server_relpath = None

                # --- NEW: enrich in place ---
                enrich_manifest(
                    mpath,
                    homepage=homepage,
                    git_origin=git_origin,
                    git_ref=git_ref,
                    server_relpath_from_repo_root=server_relpath,
                    repo_root=local.path,
                )

                log.info("wrote manifest: %s", mpath)
            except Exception as e:  # continue on per-candidate errors
                log.warning("candidate failed: %s (%s)", cdir, e)
                errors.append(f"{cdir}: {e}")

        # 6) Repo-level index.json
        repo_index = out_root / "index.json"
        # Paths in index can be relative to out_root for portability
        rel_manifest_paths = [
            str(p.relative_to(out_root)) if str(p).startswith(str(out_root)) else str(p)
            for p in manifests
        ]
        write_index(repo_index, rel_manifest_paths, additive=False)
        log.info("wrote repo index: %s (manifests=%d)", repo_index, len(manifests))

        # 7) Optional publish
        if publish:
            if publish_static is None:
                msg = "publish requested but publishers.static_index not available"
                log.error(msg)
                errors.append(msg)
            else:
                try:
                    publish_static(
                        {
                            "index": str(repo_index),
                            **{f"manifest_{i}": str(p) for i, p in enumerate(manifests)},
                        },
                        publish,
                    )
                    log.info("publish complete: %s", publish)
                except Exception as pe:  # pragma: no cover - remote dependent
                    log.exception("publish error: %s", pe)
                    errors.append(f"publish error: {pe}")

        # 8) Optional register (deferred install)
        if register:
            if not matrixhub_url:
                msg = "register=True but matrixhub_url not provided"
                log.error(msg)
                errors.append(msg)
            else:
                for mpath in manifests:
                    try:
                        with open(mpath, encoding="utf-8") as fh:
                            manifest = json.load(fh)
                        sdk_autoinstall(matrixhub_url=matrixhub_url, manifest=manifest)
                        log.info("registered manifest: %s", mpath.name)
                    except Exception as re:  # pragma: no cover - env dependent
                        log.exception("register failed for %s: %s", mpath.name, re)
                        errors.append(f"register failed for {mpath.name}: {re}")

        summary: dict[str, object] = {
            "source": local.origin,
            "prepared_path": str(local.path),
            "manifests": len(manifests),
            "candidates": len(candidates),
            "by_detector": by_detector,
            "transports": transports,
            "repo_name": local.repo_name,
            "sha": local.sha,
        }

        return HarvestResult(
            manifests=manifests, index_path=repo_index.resolve(), errors=errors, summary=summary
        )
    finally:
        # 9) Cleanup temporary workspace if prepare_source created one
        try:
            local.cleanup()
            log.debug("cleanup complete for %s", local.path)
        except Exception:  # pragma: no cover
            pass


# ----------------------------
# Candidate discovery
# ----------------------------

PY_SERVER_FILENAMES = {"server.py", "app.py", "main.py"}


def _iter_candidate_dirs(root: Path) -> Iterable[Path]:
    """Yield likely MCP server folders under *root*.

    Heuristics (cheap and safe):
      - the *root itself* if it looks like a server directory
      - any directory containing server.py/app.py/main.py
      - any directory containing package.json (Node-based MCP)
      - special folders named "servers", "packages", "examples" (scan their children)
    """
    seen: set[Path] = set()

    def add(p: Path, reason: str) -> None:
        if p.is_dir() and p not in seen:
            seen.add(p)
            log.debug("candidate:add %s (%s)", p, reason)

    # Consider root as candidate
    if _looks_like_py_server_dir(root):
        add(root, "root:py-server")
    elif _has_package_json(root):
        add(root, "root:package.json")

    # 1) direct children heuristic
    for child in root.iterdir():
        if child.is_dir() and child.name in {"servers", "packages", "examples", "apps", "services"}:
            for sub in child.rglob("*"):
                if not sub.is_dir():
                    continue
                if _looks_like_py_server_dir(sub):
                    add(sub, "rglob:py-server")
                elif _has_package_json(sub):
                    add(sub, "rglob:package.json")
        elif child.is_dir():
            if _looks_like_py_server_dir(child):
                add(child, "child:py-server")
            elif _has_package_json(child):
                add(child, "child:package.json")

    # 2) fallback: scan up to a limited depth for server.py/package.json
    # Depth guard to avoid pathological repos
    max_depth = 4
    for sub in root.rglob("*"):
        if not sub.is_dir():
            continue
        if _depth(root, sub) > max_depth:
            continue
        if _looks_like_py_server_dir(sub):
            add(sub, "fallback:py-server")
        elif _has_package_json(sub):
            add(sub, "fallback:package.json")

    # Prefer stable order
    return sorted(seen, key=lambda p: str(p))


def _depth(root: Path, sub: Path) -> int:
    try:
        return len(sub.relative_to(root).parts)
    except Exception:
        return 0


def _looks_like_py_server_dir(d: Path) -> bool:
    # quick signals
    for name in PY_SERVER_FILENAMES:
        if (d / name).exists():
            return True
    # scan small files for FastMCP/@tool
    try:
        for py in d.glob("*.py"):
            if py.stat().st_size > 256_000:
                continue
            txt = py.read_text(encoding="utf-8", errors="ignore")
            if "FastMCP(" in txt or "@mcp.tool" in txt or "from mcp.server" in txt:
                return True
    except Exception:
        pass
    return False


def _has_package_json(d: Path) -> bool:
    return (d / "package.json").exists()


# ----------------------------
# Detector chain
# ----------------------------


def _run_detectors_in_order(cdir: Path) -> tuple[DetectReport, str]:
    """Run detectors in priority order and return (report, detector_tag)."""
    # 1) FastMCP
    rep = detect_fastmcp(str(cdir))
    if _has_signal(rep):
        return rep, "fastmcp"

    # 2) Node MCP (inline heuristic)
    rep = _detect_node_mcp(str(cdir))
    if _has_signal(rep):
        return rep, "node"

    # 3) LangChain
    rep = detect_langchain(str(cdir))
    if _has_signal(rep):
        return rep, "langchain"

    # 4) Raw fallback
    rep = detect_raw_mcp(str(cdir))
    return rep, "raw"


def _has_signal(rep: DetectReport | None) -> bool:
    if not rep:
        return False
    conf = getattr(rep, "confidence", 0.0) or 0.0
    has_bits = bool(
        getattr(rep, "tools", None)
        or getattr(rep, "server_url", None)
        or getattr(rep, "resources", None)
    )
    return has_bits and conf >= 0.5


# Minimal Node MCP heuristic (kept local to avoid a whole new module for MVP)


def _detect_node_mcp(path: str) -> DetectReport:
    d = Path(path)
    out = DetectReport(confidence=0.0)
    pj = d / "package.json"
    if not pj.exists():
        return out
    try:
        data = json.loads(pj.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return out

    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    has_mcp = any(
        k.startswith("@modelcontextprotocol/") or k == "@modelcontextprotocol/sdk"
        for k in deps.keys()
    )
    scripts = data.get("scripts") or {}
    joined_scripts = "\n".join(str(v) for v in scripts.values())

    if has_mcp or "mcp" in (data.get("keywords") or []):
        out.confidence = max(out.confidence, 0.55)
        out.notes.append("node mcp indicators in package.json")

    # crude tool extraction: look for a tools/ dir or src/tools
    if (d / "tools").exists():
        out.tools.append({"id": "tool", "name": "tool"})
    if (d / "src" / "tools").exists():
        out.tools.append({"id": "tool", "name": "tool"})

    # transport/url guess from common scripts
    route = "/sse"
    if "/messages" in joined_scripts:
        route = "/messages"
    port = 6288
    for hint in ("PORT=", "--port ", "-p "):
        if hint in joined_scripts:
            try:
                # very loose parse
                tail = joined_scripts.split(hint, 1)[1].split()[0]
                port = int("".join(ch for ch in tail if ch.isdigit()))
                break
            except Exception:
                pass

    out.server_url = f"http://127.0.0.1:{port}{route}"

    # resource hint
    out.resources.append(
        {
            "id": f"{d.name}-pkg",
            "name": "package.json",
            "type": "inline",
            "uri": "file://package.json",
        }
    )

    return out


# ----------------------------
# Helpers
# ----------------------------


def _default_url() -> str:
    # offline-friendly default SSE endpoint
    return "http://127.0.0.1:6288/sse"


def _transport_tag(url: str) -> str:
    u = url.lower().strip()
    if u.endswith("/sse"):
        return "sse"
    if u.endswith("/messages"):
        return "messages"
    return "unknown"


def _slug_from_repo_and_path(local: LocalSource, cdir: Path) -> str:
    """Stable slug like: <repo-name>__path__to__dir"""
    repo = (local.repo_name or Path(local.path).name).lower().replace(" ", "-")
    try:
        rel = cdir.relative_to(local.path).as_posix()
    except Exception:
        rel = cdir.as_posix()
    safe = rel.strip("/").replace("/", "__").replace(" ", "-")
    return f"{repo}__{safe}" if safe else repo


def _first_existing(*candidates: Path) -> Path | None:
    for c in candidates:
        try:
            if c.exists():
                return c
        except Exception:
            continue
    return None
