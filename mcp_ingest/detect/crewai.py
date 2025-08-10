from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .base import DetectReport

try:  # optional YAML parsing (graceful degrade)
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

__all__ = ["detect_path"]

_CW_IMPORT_HINTS = ("import crewai", "from crewai ")
_AGENT_CALL = "Agent"
_TASK_CALL = "Task"


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


def _text_has_cw_hints(text: str) -> bool:
    return any(h in text for h in _CW_IMPORT_HINTS)


def _load_yaml(path: Path) -> dict[str, Any] | None:
    if yaml is None:
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))  # type: ignore
    except Exception:
        return None


def detect_path(source: str) -> DetectReport:
    root = Path(source).expanduser().resolve()
    files = _walk_py(root)

    rep = DetectReport(confidence=0.0, notes=[])

    # Parse Python first
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not _text_has_cw_hints(text) and _AGENT_CALL not in text and _TASK_CALL not in text:
            continue
        try:
            tree = ast.parse(text)
        except Exception:
            continue

        # Agent(name=..., role=..., backstory=..., tools=[...])
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) == _AGENT_CALL:
                nm = rl = bs = None
                for kw in getattr(node, "keywords", []) or []:
                    if (
                        kw.arg == "name"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                    ):
                        nm = kw.value.value
                    if (
                        kw.arg == "role"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                    ):
                        rl = kw.value.value
                    if (
                        kw.arg == "backstory"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                    ):
                        bs = kw.value.value
                if nm:
                    rep.tools.append({"id": nm, "name": nm})  # treat agent as callable tool proxy
                    if rl or bs:
                        txt = " | ".join(x for x in [rl, bs] if x)
                        rep.prompts.append({"id": f"{nm}-prompt", "name": nm, "text": txt[:200]})
                    rep.confidence = max(rep.confidence, 0.6)

        # Task(description=..., expected_output=...)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) == _TASK_CALL:
                desc = None
                for kw in getattr(node, "keywords", []) or []:
                    if (
                        kw.arg == "description"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                    ):
                        desc = kw.value.value
                        break
                if desc and len(desc) >= 20:
                    rep.prompts.append({"id": f"{f.stem}-task", "name": "task", "text": desc[:200]})
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

    # Parse YAML crew files (agents.yaml, tasks.yaml, crew.yaml)
    for y in [p for p in root.rglob("*.yaml") if p.is_file()]:
        if y.name not in {"agents.yaml", "tasks.yaml", "crew.yaml"}:
            continue
        data = _load_yaml(y)
        if not isinstance(data, dict):
            continue
        # Heuristics: top-level keys may map to agents/tasks definitions
        for k, v in data.items():
            if not isinstance(v, dict):
                continue
            nm = v.get("name") or k
            if y.name.startswith("agents"):
                rep.tools.append({"id": nm, "name": nm})
                txt = " | ".join(str(v.get(x) or "") for x in ("role", "backstory") if v.get(x))
                if txt:
                    rep.prompts.append({"id": f"{nm}-prompt", "name": nm, "text": txt[:200]})
                rep.confidence = max(rep.confidence, 0.55)
            elif y.name.startswith("tasks"):
                desc = str(v.get("description") or "")
                if len(desc) >= 20:
                    rep.prompts.append({"id": f"{nm}-task", "name": nm, "text": desc[:200]})
                    rep.confidence = max(rep.confidence, 0.55)

    if rep.tools or rep.prompts:
        rep.notes.append("framework: crewai")
    return rep
