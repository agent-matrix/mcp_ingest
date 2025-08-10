from __future__ import annotations
"""mcp_ingest.cli

User-facing CLI for the mcp-ingest SDK. Commands:
  - detect         : offline detector (FastMCP for MVP)
  - describe       : write manifest.json + index.json
  - register       : POST manifest to MatrixHub /catalog/install
  - pack           : detect -> describe -> (optional) register
  - harvest-repo   : repo-wide scan (dir|git|zip) -> many manifests + repo index

All commands print structured JSON to stdout (CI-friendly). Python 3.11+.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from .sdk import describe as sdk_describe, autoinstall as sdk_autoinstall
from .detect.fastmcp import detect_path as detect_fastmcp

# Optional (Stage-1+: repo harvester)
try:  # pragma: no cover - optional dependency within the package
    from .harvest.repo import harvest_repo  # type: ignore
except Exception:  # pragma: no cover
    harvest_repo = None  # type: ignore


# ------------------------- helpers -------------------------

def _print_json(obj: Any) -> None:
    json.dump(obj, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _parse_kv_list(values: List[str] | None) -> List[Dict[str, Any]]:
    """Parse repeated --resource 'k=v,k=v' flags into list[dict]."""
    out: List[Dict[str, Any]] = []
    if not values:
        return out
    for item in values:
        entry: Dict[str, Any] = {}
        for kv in (item.split(",") if item else []):
            if "=" in kv:
                k, v = kv.split("=", 1)
                entry[k.strip()] = v.strip()
        if entry:
            out.append(entry)
    return out


# ------------------------- commands -------------------------

def cmd_detect(args: argparse.Namespace) -> None:
    report = detect_fastmcp(args.source)
    _print_json({
        "detector": "fastmcp",
        "report": report.to_dict(),
    })


def cmd_describe(args: argparse.Namespace) -> None:
    tools: List[str] = [t for t in (args.tools or []) if t]
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

    result: Dict[str, Any] = {"detected": report.to_dict(), "describe": out}

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
    payload: Dict[str, Any] = {
        "manifests": [str(p) for p in getattr(res, "manifests", [])],
        "index_path": str(getattr(res, "index_path", "")),
        "errors": list(getattr(res, "errors", [])),
        "summary": getattr(res, "summary", {}),
    }
    _print_json(payload)


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
    s.add_argument("--resource", action="append", help="resource as key=value pairs, comma-separated (repeatable)")
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
    h.add_argument("--publish", default=None, help="publish destination e.g. s3://bucket/prefix or ghpages://user/repo")
    h.add_argument("--register", action="store_true", help="register to MatrixHub after describe")
    h.add_argument("--matrixhub", default=None, help="MatrixHub base URL if --register is set")
    h.set_defaults(func=cmd_harvest_repo)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
