from __future__ import annotations

import ast
from pathlib import Path

from ..utils.jsonschema import infer_schema_from_ast_func
from .base import DetectReport

__all__ = ["detect_path"]

# Broad match for new and legacy import paths
_LI_IMPORT_HINTS = (
    "import llama_index",
    "from llama_index ",
    "from llama_index.core ",
    "from llama_index.agent ",
    "from llama_index.llms ",
)

# Agent/runner constructs commonly used
_LI_AGENT_NAMES = {
    "ReActAgent",
    "OpenAIAgent",
    "AgentRunner",
    "QueryEngineTool",
    "FunctionTool",
}


def _walk_py(root: Path) -> list[Path]:
    if root.is_file() and root.suffix == ".py":
        return [root]
    return [p for p in root.rglob("*.py") if p.is_file()]


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _collect_functions(tree: ast.AST) -> dict[str, ast.FunctionDef]:
    out: dict[str, ast.FunctionDef] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef):
            out[n.name] = n
    return out


def _text_has_li_hints(text: str) -> bool:
    return any(h in text for h in _LI_IMPORT_HINTS)


def detect_path(source: str) -> DetectReport:
    root = Path(source).expanduser().resolve()
    files = _walk_py(root)

    rep = DetectReport(confidence=0.0, notes=[])

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        is_li = _text_has_li_hints(text)
        if not is_li:
            # Skip files that do not reference LlamaIndex at all
            continue

        try:
            tree = ast.parse(text)
        except Exception:
            continue

        funcs = _collect_functions(tree)

        # Note: ServiceContext/Settings discovery (adds confidence)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) in {
                "ServiceContext",
                "Settings",
            }:
                rep.notes.append(f"llamaindex config: {_call_name(node.func)} in {f.name}")
                rep.confidence = max(rep.confidence, 0.55)

        # Tools defined via FunctionTool.from_defaults(fn=...)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) == "from_defaults":
                # Ensure the callee is FunctionTool.from_defaults
                base = getattr(node.func, "value", None)
                if isinstance(base, ast.Name) and base.id != "FunctionTool":
                    continue
                if isinstance(base, ast.Attribute) and base.attr != "FunctionTool":
                    # e.g., tools.FunctionTool.from_defaults
                    if getattr(base, "attr", None) != "FunctionTool":
                        continue
                tool_name: str | None = None
                fn_name: str | None = None
                for kw in getattr(node, "keywords", []) or []:
                    if (
                        kw.arg == "name"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                    ):
                        tool_name = kw.value.value
                    if kw.arg in {"fn", "func"} and isinstance(kw.value, ast.Name):
                        fn_name = kw.value.id
                if fn_name and fn_name in funcs:
                    schema = infer_schema_from_ast_func(funcs[fn_name])
                else:
                    schema = {"type": "object", "properties": {}}
                tname = tool_name or fn_name or "function_tool"
                rep.tools.append({"id": tname, "name": tname, "input_schema": schema})
                rep.confidence = max(rep.confidence, 0.7)

        # QueryEngineTool(name=..., description=...)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) == "QueryEngineTool":
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

        # Prompt-like strings in variables named *prompt*
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = [getattr(t, "id", None) for t in node.targets if hasattr(t, "id")]
                if not any(t and "prompt" in t.lower() for t in targets if t):
                    continue
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    s = node.value.value
                    if len(s) >= 20:
                        rep.prompts.append(
                            {"id": f"{f.stem}-prompt", "name": "prompt", "text": s[:200]}
                        )
                        rep.confidence = max(rep.confidence, 0.6)

        # Agent construct hints
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) in _LI_AGENT_NAMES:
                rep.notes.append(f"agent construct: {_call_name(node.func)} in {f.name}")
                rep.confidence = max(rep.confidence, 0.7)

        # Source pointer as a resource
        if f.name in {"server.py", "app.py", "main.py"}:
            rep.resources.append(
                {
                    "id": f"{f.stem}-source",
                    "name": "server source",
                    "type": "inline",
                    "uri": f"file://{f.name}",
                }
            )

    if rep.tools or rep.prompts:
        rep.notes.append("framework: llamaindex")
    return rep
