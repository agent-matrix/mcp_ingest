
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from typing import Any, Dict, List

from .sdk import describe as sdk_describe, autoinstall as sdk_autoinstall
from .detect.fastmcp import detect_path as detect_fastmcp


def _print_json(obj: Any) -> None:
    json.dump(obj, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def cmd_detect(args: argparse.Namespace) -> None:
    report = detect_fastmcp(args.source)
    _print_json({
        "detector": "fastmcp",
        "report": report.to_dict(),
    })


def cmd_describe(args: argparse.Namespace) -> None:
    tools: List[str] = [t for t in (args.tools or []) if t]
    resources: List[Dict[str, Any]] = []
    for r in (args.resource or []):
        # very light parser for KEY=VAL,KEY=VAL
        entry: Dict[str, Any] = {}
        for kv in r.split(,):
            if = in kv:
                k, v = kv.split(=, 1)
                entry[k.strip()] = v.strip()
        if entry:
            resources.append(entry)

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
    import json as _json
    manifest = _json.loads(mpath.read_text(encoding="utf-8"))

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
        import json as _json
        mpath = Path(out["manifest_path"]).expanduser()
        manifest = _json.loads(mpath.read_text(encoding="utf-8"))
        res = sdk_autoinstall(
            matrixhub_url=args.matrixhub,
            manifest=manifest,
            entity_uid=args.entity_uid,
            target=args.target,
            token=args.token,
        )
        result["register"] = res

    _print_json(result)


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

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

