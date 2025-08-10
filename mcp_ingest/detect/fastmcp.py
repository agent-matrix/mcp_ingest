from __future__ import annotations

import ast
from pathlib import Path

from ..utils.jsonschema import infer_schema_from_ast_func
from .base import DetectReport


def _walk_py_files(root: Path) -> list[Path]:
    if root.is_file() and root.suffix == ".py":
        return [root]
    return [p for p in root.rglob("*.py") if p.is_file()]


def _is_tool_decorator(dec: ast.expr) -> bool:
    # Matches @tool, @mcp.tool, @fastmcp.tool, etc.
    if isinstance(dec, ast.Name):
        return dec.id == "tool"
    if isinstance(dec, ast.Attribute):
        return dec.attr == "tool"
    return False


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _string_or_none(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def detect_path(source: str) -> DetectReport:
    root = Path(source).expanduser().resolve()
    files = _walk_py_files(root)

    report = DetectReport()

    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except Exception:
            continue

        # FastMCP constructor & run() hints
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) == "FastMCP":
                # try to pick name from first arg or kwarg name="..."
                name = None
                if node.args:
                    name = _string_or_none(node.args[0])
                for kw in getattr(node, "keywords", []) or []:
                    if kw.arg == "name":
                        name = _string_or_none(kw.value) or name
                if name:
                    report.notes.append(f"FastMCP server name: {name}")
                report.confidence = max(report.confidence, 0.6)

        # Tools via decorators
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if any(_is_tool_decorator(d) for d in node.decorator_list):
                    tname = node.name.replace("_", "-")
                    schema = infer_schema_from_ast_func(node)
                    report.tools.append(
                        {
                            "id": tname,
                            "name": tname,
                            "input_schema": schema,
                        }
                    )
                    report.confidence = max(report.confidence, 0.8)

        # Optionally, detect a server.py to add as resource reference
        if f.name == "server.py":
            report.resources.append(
                {
                    "id": f"{f.parent.name}-server",
                    "name": "server source",
                    "type": "inline",
                    "uri": f"file://{f.name}",
                }
            )

    if report.tools:
        report.notes.append(f"found {len(report.tools)} tool(s) via @tool")

    return report
