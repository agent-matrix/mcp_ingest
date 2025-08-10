from __future__ import annotations

import ast
from pathlib import Path

from ..utils.jsonschema import infer_schema_from_ast_func
from .base import DetectReport

__all__ = ["detect_path"]


_LANGCHAIN_HINTS = (
    "import langchain",
    "from langchain ",
)
_TOOL_CLASS_NAMES = {"Tool", "StructuredTool"}
_TOOL_DECORATOR_NAMES = {"tool"}  # @tool from langchain.tools
_PROMPT_HINTS = ("PromptTemplate", "from langchain.prompts")


def _walk_py(root: Path) -> list[Path]:
    if root.is_file() and root.suffix == ".py":
        return [root]
    return [p for p in root.rglob("*.py") if p.is_file()]


def _is_langchain_file(text: str) -> bool:
    return any(h in text for h in _LANGCHAIN_HINTS)


def _dec_names(fn: ast.FunctionDef) -> list[str]:
    out: list[str] = []
    for d in fn.decorator_list:
        if isinstance(d, ast.Name):
            out.append(d.id)
        elif isinstance(d, ast.Attribute):
            out.append(d.attr)
    return out


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def detect_path(source: str) -> DetectReport:
    root = Path(source).expanduser().resolve()
    files = _walk_py(root)
    rep = DetectReport(confidence=0.0, notes=[])

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        is_lc = _is_langchain_file(text)
        if not is_lc and "@tool" not in text:
            continue

        try:
            tree = ast.parse(text)
        except Exception:
            continue

        # 1) Functions with @tool
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                decs = _dec_names(node)
                if any(d in _TOOL_DECORATOR_NAMES for d in decs):
                    tname = node.name.replace("_", "-")
                    schema = infer_schema_from_ast_func(node)
                    rep.tools.append({"id": tname, "name": tname, "input_schema": schema})
                    rep.confidence = max(rep.confidence, 0.7)

        # 2) Tool/StructuredTool instances: Tool(name=..., func=...)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) in _TOOL_CLASS_NAMES:
                tname = None
                for kw in getattr(node, "keywords", []) or []:
                    if (
                        kw.arg == "name"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                    ):
                        tname = kw.value.value
                        break
                if tname:
                    rep.tools.append({"id": tname, "name": tname})
                    rep.confidence = max(rep.confidence, 0.65)

        # 3) Prompt templates (best-effort)
        if any(h in text for h in _PROMPT_HINTS):
            rep.prompts.append(
                {"id": f"{f.stem}-prompt", "name": "prompt", "uri": f"file://{f.name}"}
            )
            rep.confidence = max(rep.confidence, 0.6)

        # 4) Server resource hint (if server.py present)
        if f.name == "server.py":
            rep.resources.append(
                {
                    "id": f"{f.parent.name}-server",
                    "name": "server source",
                    "type": "inline",
                    "uri": f"file://{f.name}",
                }
            )

        if is_lc:
            rep.notes.append(f"langchain usage in {f.name}")

    if rep.tools:
        rep.notes.append(f"found {len(rep.tools)} tool(s) via langchain patterns")
    if rep.prompts:
        rep.notes.append(f"found {len(rep.prompts)} prompt(s)")

    return rep
