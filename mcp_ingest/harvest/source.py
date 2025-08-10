from __future__ import annotations

"""
Orchestrator that turns README candidates into per-repo harvests and one merged
catalog. This is the glue used by the `harvest-source` CLI command.

Flow:
  1) Read README of the given GitHub repo and extract all GitHub targets.
  2) Convert targets to CandidatePlans (repo or tree-with-ref-and-subpath).
  3) Execute each plan in parallel, calling `harvest_repo(...)` to generate
     per-server manifests and a per-plan index.json under its own out folder.
  4) Merge all child indexes into a single repo-level index.json under the
     top-level out_dir.
  5) Optionally register each manifest to MatrixHub (idempotent).

This module purposely catches and aggregates errors so a single failing
candidate does not stop the entire harvest.
"""

import concurrent.futures as _fut
import json
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from ..harvest.repo import HarvestResult, harvest_repo
from ..publishers.static_index import merge_indexes
from ..register.hub_client import HubClient
from ..utils.extractor import (
    RepoTarget,
    extract_github_repo_links_from_readme,
)
from ..utils.github_archive import download_ref

__all__ = [
    "CandidatePlan",
    "CandidateResult",
    "harvest_source",
]


@dataclass(frozen=True)
class CandidatePlan:
    kind: Literal["repo", "tree"]
    display: str
    repo_url: str
    ref: str | None = None
    subpath: str | None = None


@dataclass
class CandidateResult:
    plan: CandidatePlan
    manifests: list[str]
    index_path: str | None
    errors: list[str]
    by_detector: dict[str, int]
    transports: dict[str, int]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _slug(s: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in s]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "repo"


def _parse_owner_repo(repo_url: str) -> tuple[str, str]:
    if repo_url.startswith("git@github.com:"):
        repo_url = repo_url.replace("git@github.com:", "https://github.com/")
    p = urlparse(repo_url)
    if p.netloc != "github.com":
        raise ValueError("harvest_source currently supports github.com only")
    parts = [x for x in p.path.split("/") if x]
    if len(parts) < 2:
        raise ValueError("invalid GitHub repo URL")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


# Very light manifest parsing to collect transport stats if needed.


def _classify_transport_from_manifest(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        server = (data.get("mcp_registration") or {}).get("server") or {}
        if isinstance(server, dict):
            if server.get("exec"):
                return "stdio"
            url = (server.get("url") or "").lower()
            if "/sse" in url:
                return "sse"
            if "/messages" in url or "ws" in url:
                return "messages"
    except Exception:
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def _plans_from_targets(repo_url: str, targets: Sequence[RepoTarget]) -> list[CandidatePlan]:
    plans: list[CandidatePlan] = []
    # Always include the input repo itself first
    owner, repo = _parse_owner_repo(repo_url)
    base_display = f"{owner}/{repo}"
    plans.append(CandidatePlan(kind="repo", display=base_display, repo_url=repo_url))

    for t in targets:
        if t.ref or t.subpath:
            disp = f"{t.owner}/{t.repo}#{t.ref or 'HEAD'}" + (f"/{t.subpath}" if t.subpath else "")
            plans.append(
                CandidatePlan(
                    kind="tree", display=disp, repo_url=t.repo_url, ref=t.ref, subpath=t.subpath
                )
            )
        else:
            disp = f"{t.owner}/{t.repo}"
            # avoid duplicating the base repo
            if disp == base_display:
                continue
            plans.append(CandidatePlan(kind="repo", display=disp, repo_url=t.repo_url))

    # Deduplicate by (kind, repo_url, ref, subpath)
    seen = set()
    out: list[CandidatePlan] = []
    for p in plans:
        key = (p.kind, p.repo_url, p.ref, p.subpath)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# Execution per plan
# ---------------------------------------------------------------------------


def _run_plan(
    plan: CandidatePlan, *, out_root: Path, register: bool, matrixhub: str | None
) -> CandidateResult:
    plan_out = out_root / _slug(plan.display)
    plan_out.mkdir(parents=True, exist_ok=True)

    manifests: list[str] = []
    errors: list[str] = []
    idx_path: str | None = None
    by_detector: dict[str, int] = {}
    transports: dict[str, int] = {}

    try:
        if plan.kind == "repo":
            res: HarvestResult = harvest_repo(plan.repo_url, out_dir=plan_out)
            manifests = [str(Path(p)) for p in (res.manifests or [])]
            idx_path = str(res.index_path) if res.index_path else None
            # Optional registration
            if register and matrixhub and manifests:
                _register_many(matrixhub, manifests)
            # Summaries
            by_detector.update((res.summary or {}).get("by_detector", {}))
            transports.update((res.summary or {}).get("transports", {}))

        elif plan.kind == "tree":
            owner, repo = _parse_owner_repo(plan.repo_url)
            ref = plan.ref or "HEAD"
            with tempfile.TemporaryDirectory(prefix="mcp-arc-") as tdir:
                root = download_ref(owner, repo, ref, tdir)
                local = Path(root) / (plan.subpath or "")
                if not local.exists():
                    raise FileNotFoundError(f"subpath not found in archive: {plan.subpath}")
                res: HarvestResult = harvest_repo(str(local), out_dir=plan_out)
                manifests = [str(Path(p)) for p in (res.manifests or [])]
                idx_path = str(res.index_path) if res.index_path else None
                if register and matrixhub and manifests:
                    _register_many(matrixhub, manifests)
                by_detector.update((res.summary or {}).get("by_detector", {}))
                transports.update((res.summary or {}).get("transports", {}))
        else:  # pragma: no cover
            errors.append(f"unknown plan kind: {plan.kind}")

        # If transport stats missing, compute light ones from manifests
        if manifests and not transports:
            tally: dict[str, int] = {}
            for mp in manifests:
                t = _classify_transport_from_manifest(Path(mp))
                tally[t] = tally.get(t, 0) + 1
            transports = tally

    except Exception as e:  # keep going, record error
        errors.append(str(e))

    return CandidateResult(
        plan=plan,
        manifests=manifests,
        index_path=idx_path,
        errors=errors,
        by_detector=by_detector,
        transports=transports,
    )


def _register_many(matrixhub_url: str, manifest_paths: Sequence[str]) -> None:
    client = HubClient(matrixhub_url)
    for mp in manifest_paths:
        try:
            data = json.loads(Path(mp).read_text(encoding="utf-8"))
            entity_uid = (
                f"{data.get('type', 'mcp_server')}:{data.get('id')}@{data.get('version', '0.1.0')}"
            )
            client.install_manifest(entity_uid=entity_uid, target="./", manifest=data)
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def harvest_source(
    repo_url: str,
    out_dir: str | Path,
    *,
    yes: bool = False,
    max_parallel: int = 4,
    only_github: bool = True,  # reserved flag; extractor already filters to GitHub
    register: bool = False,
    matrixhub: str | None = None,
    log_file: str | None = None,  # reserved for future structured logs
) -> dict:
    """Harvest a GitHub repo *and* all GitHub repos linked in its README.

    Returns a JSON-serializable summary with merged index and per-plan results.
    """
    out_root = Path(out_dir).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    # 1) Extract README targets
    targets: list[RepoTarget] = extract_github_repo_links_from_readme(repo_url)

    # 2) Build plans (include base repo first)
    plans: list[CandidatePlan] = _plans_from_targets(repo_url, targets)
    if not yes:
        # Print a short preview (caller/CLI can choose to ask beforehand)
        preview = [p.display for p in plans]
        # In library mode we just proceed when yes=True, otherwise proceed anyway.
        _ = preview  # placeholder if we later add interactive gating here

    # 3) Execute plans in parallel
    results: list[CandidateResult] = []
    with _fut.ThreadPoolExecutor(max_workers=max_parallel) as ex:
        futs = [
            ex.submit(_run_plan, plan, out_root=out_root, register=register, matrixhub=matrixhub)
            for plan in plans
        ]
        for f in _fut.as_completed(futs):
            try:
                results.append(f.result())
            except Exception as e:  # pragma: no cover
                results.append(
                    CandidateResult(
                        plan=CandidatePlan(kind="repo", display="<unknown>", repo_url=""),
                        manifests=[],
                        index_path=None,
                        errors=[str(e)],
                        by_detector={},
                        transports={},
                    )
                )

    # 4) Merge child indexes -> top-level index.json
    child_indexes = [r.index_path for r in results if r.index_path]
    manifest_lists = [r.manifests for r in results if r.manifests]
    merged = (
        merge_indexes([Path(p) for p in child_indexes])
        if child_indexes
        else {"manifests": sum(manifest_lists, [])}
    )

    top_index = out_root / "index.json"
    top_index.write_text(json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8")

    # 5) Build summary
    all_manifests = merged.get("manifests", [])
    err_list = [err for r in results for err in (r.errors or [])]

    # Aggregate simple counts
    by_detector: dict[str, int] = {}
    transports: dict[str, int] = {}
    for r in results:
        for k, v in (r.by_detector or {}).items():
            by_detector[k] = by_detector.get(k, 0) + int(v)
        for k, v in (r.transports or {}).items():
            transports[k] = transports.get(k, 0) + int(v)

    summary = {
        "index_path": str(top_index),
        "manifests_count": len(all_manifests),
        "manifests": all_manifests,
        "errors": err_list,
        "by_detector": by_detector,
        "transports": transports,
        "plans": [
            {
                "display": r.plan.display,
                "kind": r.plan.kind,
                "manifests": r.manifests,
                "errors": r.errors,
            }
            for r in results
        ],
    }

    return summary
