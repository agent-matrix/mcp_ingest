from __future__ import annotations

import ast
from pathlib import Path

from ..utils.jsonschema import infer_schema_from_ast_func
from .base import DetectReport

__all__ = ["detect_path"]

_AG_IMPORT_HINTS = (
    "import autogen",
    "from autogen ",
)
_AGENT_CLASSES = {"AssistantAgent", "UserProxyAgent", "GroupChat", "GroupChatManager"}


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


def _text_has_ag_hints(text: str) -> bool:
    return any(h in text for h in _AG_IMPORT_HINTS)


def detect_path(source: str) -> DetectReport:
    root = Path(source).expanduser().resolve()
    files = _walk_py(root)

    rep = DetectReport(confidence=0.0, notes=[])
    agent_count = 0

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not _text_has_ag_hints(text) and not any(a in text for a in _AGENT_CLASSES):
            continue

        try:
            tree = ast.parse(text)
        except Exception:
            continue

        funcs = _collect_functions(tree)

        # Count agent constructs
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) in _AGENT_CLASSES:
                agent_count += 1
                rep.notes.append(f"autogen agent: {_call_name(node.func)} in {f.name}")
                rep.confidence = max(rep.confidence, 0.55)

        # agent.register_function(fn=...) or .register_tool(...)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"register_function", "register_tool"}:
                    tname: str | None = None
                    fn_name: str | None = None
                    for kw in getattr(node, "keywords", []) or []:
                        if (
                            kw.arg in {"name", "tool_name"}
                            and isinstance(kw.value, ast.Constant)
                            and isinstance(kw.value.value, str)
                        ):
                            tname = kw.value.value
                        if kw.arg in {"fn", "func"} and isinstance(kw.value, ast.Name):
                            fn_name = kw.value.id
                    if fn_name and fn_name in funcs:
                        schema = infer_schema_from_ast_func(funcs[fn_name])
                    else:
                        schema = {"type": "object", "properties": {}}
                    tool_id = tname or fn_name or "autogen-tool"
                    rep.tools.append({"id": tool_id, "name": tool_id, "input_schema": schema})
                    rep.confidence = max(rep.confidence, 0.65)

        # system/system_message style prompt strings
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                names = [getattr(t, "id", "") for t in node.targets if hasattr(t, "id")]
                if not any("system" in (n or "").lower() for n in names):
                    continue
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    s = node.value.value
                    if len(s) >= 20:
                        rep.prompts.append(
                            {"id": f"{f.stem}-system", "name": "system", "text": s[:200]}
                        )
                        rep.confidence = max(rep.confidence, 0.6)

        if f.name in {"server.py", "main.py", "app.py"}:
            rep.resources.append(
                {
                    "id": f"{f.stem}-source",
                    "name": "server source",
                    "type": "inline",
                    "uri": f"file://{f.name}",
                }
            )

    if agent_count >= 2:
        rep.notes.append("pattern: multi-agent")
        rep.confidence = max(rep.confidence, 0.7)

    if rep.tools or agent_count:
        rep.notes.append("framework: autogen")
    return rep
