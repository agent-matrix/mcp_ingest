from __future__ import annotations

"""mcp_ingest.cli

User-facing CLI for the mcp-ingest SDK. Commands:
  - detect         : offline detector (FastMCP for MVP)
  - describe       : write manifest.json + index.json
  - register       : POST manifest to MatrixHub /catalog/install
  - pack           : detect -> describe -> (optional) register
  - harvest-repo   : repo-wide scan (dir|git|zip) -> many manifests + repo index
  - harvest-source : extract README links from a GitHub repo -> harvest each -> merge catalog

All commands print structured JSON to stdout (CI-friendly). Python 3.11+.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .detect.fastmcp import detect_path as detect_fastmcp
from .sdk import autoinstall as sdk_autoinstall
from .sdk import describe as sdk_describe

# Optional (Stage-1+: repo harvester)
try:  # pragma: no cover - optional dependency within the package
    from .harvest.repo import harvest_repo  # type: ignore
except Exception:  # pragma: no cover
    harvest_repo = None  # type: ignore

# Optional (Stage-2+: README extractor + source orchestrator)
try:  # pragma: no cover - optional import until feature lands
    from .harvest.source import harvest_source  # type: ignore
except Exception:  # pragma: no cover
    harvest_source = None  # type: ignore


# ------------------------- helpers -------------------------


def _print_json(obj: Any) -> None:
    json.dump(obj, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _parse_kv_list(values: list[str] | None) -> list[dict[str, Any]]:
    """Parse repeated --resource 'k=v,k=v' flags into list[dict]."""
    out: list[dict[str, Any]] = []
    if not values:
        return out
    for item in values:
        entry: dict[str, Any] = {}
        for kv in item.split(",") if item else []:
            if "=" in kv:
                k, v = kv.split("=", 1)
                entry[k.strip()] = v.strip()
        if entry:
            out.append(entry)
    return out


# ------------------------- commands -------------------------


def cmd_detect(args: argparse.Namespace) -> None:
    report = detect_fastmcp(args.source)
    _print_json(
        {
            "detector": "fastmcp",
            "report": report.to_dict(),
        }
    )


def cmd_describe(args: argparse.Namespace) -> None:
    tools: list[str] = [t for t in (args.tools or []) if t]
    resources = _parse_kv_list(args.resource)

    out = sdk_describe(
        name=args.name,
        url=args.url,
        tools=tools or None,
        resources=resources or None,
        description=args.description or "",
        version=args.version,
        entity_id=args.entity_id,
        entity_name=args.entity_name,
        out_dir=args.out,
    )
    _print_json({"ok": True, **out})


def cmd_register(args: argparse.Namespace) -> None:
    mpath = Path(args.manifest).expanduser()
    if not mpath.exists():
        raise SystemExit(f"manifest not found: {mpath}")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))

    res = sdk_autoinstall(
        matrixhub_url=args.matrixhub,
        manifest=manifest,
        entity_uid=args.entity_uid,
        target=args.target,
        token=args.token,
    )
    _print_json(res)


def cmd_pack(args: argparse.Namespace) -> None:
    # 1) Detect (fastmcp only for now)
    report = detect_fastmcp(args.source)

    # 2) Synthesize describe inputs
    name = args.name or report.suggest_name(default="mcp-server")
    url = args.url or report.server_url or ""
    if not url and args.register:
        raise SystemExit("--url is required for --register")

    tools = [t.get("name") or t.get("id") for t in report.tools] if report.tools else []

    out = sdk_describe(
        name=name,
        url=url,
        tools=[t for t in tools if t],
        resources=report.resources or None,
        description=args.description or report.summarize_description(),
        version=args.version,
        out_dir=args.out,
    )

    result: dict[str, Any] = {"detected": report.to_dict(), "describe": out}

    # 3) Optional register
    if args.register:
        mpath = Path(out["manifest_path"]).expanduser()
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        res = sdk_autoinstall(
            matrixhub_url=args.matrixhub,
            manifest=manifest,
            entity_uid=args.entity_uid,
            target=args.target,
            token=args.token,
        )
        result["register"] = res

    _print_json(result)


def cmd_harvest_repo(args: argparse.Namespace) -> None:
    if harvest_repo is None:  # pragma: no cover
        raise SystemExit("harvest-repo is unavailable: .harvest.repo not found in package")

    if args.register and not args.matrixhub:
        raise SystemExit("--matrixhub is required when using --register")

    # Run the repo-wide orchestrator
    res = harvest_repo(
        args.source,
        out_dir=args.out,
        publish=args.publish,
        register=bool(args.register),
        matrixhub_url=args.matrixhub,
    )

    # Convert dataclass-like to plain dict for JSON
    payload: dict[str, Any] = {
        "manifests": [str(p) for p in getattr(res, "manifests", [])],
        "index_path": str(getattr(res, "index_path", "")),
        "errors": list(getattr(res, "errors", [])),
        "summary": getattr(res, "summary", {}),
    }
    _print_json(payload)


def cmd_harvest_source(args: argparse.Namespace) -> None:
    if harvest_source is None:  # pragma: no cover
        raise SystemExit("harvest-source is unavailable: .harvest.source not found in package")

    if args.register and not args.matrixhub:
        raise SystemExit("--matrixhub is required when using --register")

    summary = harvest_source(
        repo_url=args.repo,
        out_dir=args.out,
        yes=bool(args.yes),
        max_parallel=int(args.max_parallel),
        only_github=bool(args.only_github),
        register=bool(args.register),
        matrixhub=args.matrixhub,
        log_file=args.log_file,
    )

    _print_json(summary)

    # Exit non-zero on total failure (no manifests and there were errors)
    if summary.get("manifests_count", 0) == 0 and summary.get("errors"):
        raise SystemExit(2)


# ------------------------- parser -------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mcp-ingest", description="MCP ingest SDK/CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    # detect
    d = sub.add_parser("detect", help="Detect FastMCP server metadata (offline)")
    d.add_argument("source", help="file or directory to scan")
    d.set_defaults(func=cmd_detect)

    # describe
    s = sub.add_parser("describe", help="Write manifest.json + index.json")
    s.add_argument("name")
    s.add_argument("url")
    s.add_argument("--tools", nargs="*", help="tool names (optional)")
    s.add_argument(
        "--resource",
        action="append",
        help="resource as key=value pairs, comma-separated (repeatable)",
    )
    s.add_argument("--description", default="")
    s.add_argument("--version", default="0.1.0")
    s.add_argument("--entity-id")
    s.add_argument("--entity-name")
    s.add_argument("--out", default=".")
    s.set_defaults(func=cmd_describe)

    # register
    r = sub.add_parser("register", help="Register manifest to MatrixHub /catalog/install")
    r.add_argument("--matrixhub", required=True)
    r.add_argument("--manifest", default="./manifest.json")
    r.add_argument("--entity-uid")
    r.add_argument("--target", default="./")
    r.add_argument("--token")
    r.set_defaults(func=cmd_register)

    # pack (detect -> describe -> optional register)
    k = sub.add_parser("pack", help="Detect, describe, and optionally register in one go")
    k.add_argument("source", help="file or directory to scan")
    k.add_argument("--name")
    k.add_argument("--url")
    k.add_argument("--description", default="")
    k.add_argument("--version", default="0.1.0")
    k.add_argument("--out", default=".")
    k.add_argument("--register", action="store_true")
    k.add_argument("--matrixhub")
    k.add_argument("--entity-uid")
    k.add_argument("--target", default="./")
    k.add_argument("--token")
    k.set_defaults(func=cmd_pack)

    # harvest-repo (repo-wide discovery -> many manifests)
    h = sub.add_parser(
        "harvest-repo",
        help="Scan a repo (dir|git|zip), generate per-server manifests and a repo-level index",
    )
    h.add_argument("source", help="path | git URL | zip URL of a repo to harvest")
    h.add_argument("--out", default="dist/servers", help="output directory for artifacts")
    h.add_argument(
        "--publish",
        default=None,
        help="publish destination e.g. s3://bucket/prefix or ghpages://user/repo",
    )
    h.add_argument("--register", action="store_true", help="register to MatrixHub after describe")
    h.add_argument("--matrixhub", default=None, help="MatrixHub base URL if --register is set")
    h.set_defaults(func=cmd_harvest_repo)

    # harvest-source (README extractor -> multi-repo harvest -> merge)
    hs = sub.add_parser(
        "harvest-source",
        help=(
            "Extract README links from a GitHub repo, harvest each candidate, and merge into one catalog"
        ),
    )
    hs.add_argument("repo", help="GitHub repository URL to read the README from")
    hs.add_argument("--out", required=True, help="Output directory for merged catalog")
    hs.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    hs.add_argument(
        "--max-parallel", type=int, default=4, help="Parallelism for candidate harvests"
    )
    hs.add_argument(
        "--only-github",
        action="store_true",
        default=False,
        help="Ignore non-github.com links in README",
    )
    hs.add_argument("--register", action="store_true", help="Register each manifest to MatrixHub")
    hs.add_argument(
        "--matrixhub", default=None, help="MatrixHub base URL (required for --register)"
    )
    hs.add_argument(
        "-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv)"
    )
    hs.add_argument("--log-file", default=None, help="Optional log file path for the orchestrator")
    hs.set_defaults(func=cmd_harvest_source)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
