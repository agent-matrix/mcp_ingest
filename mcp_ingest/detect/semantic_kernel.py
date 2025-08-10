from __future__ import annotations

import ast
from pathlib import Path

from ..utils.jsonschema import infer_schema_from_ast_func
from .base import DetectReport

__all__ = ["detect_path"]

# Heuristics for Semantic Kernel usage in Python repos
_SK_IMPORT_HINTS = (
    "import semantic_kernel",
    "from semantic_kernel",
    "import sk",  # sometimes aliased
    "from sk ",
)
_SK_DECORATORS = {"kernel_function", "skill_function"}
_PROMPT_FILE_PATTERNS = (
    "skprompt.txt",  # common in SK samples
    "prompt.txt",
    ".prompt",
)


def _walk_py(root: Path) -> list[Path]:
    if root.is_file() and root.suffix == ".py":
        return [root]
    return [p for p in root.rglob("*.py") if p.is_file()]


def _is_sk_file(text: str) -> bool:
    t = text
    return (
        any(h in t for h in _SK_IMPORT_HINTS) or "@kernel_function" in t or "@skill_function" in t
    )


def _decorator_names(fn: ast.FunctionDef) -> list[str]:
    out: list[str] = []
    for d in fn.decorator_list:
        if isinstance(d, ast.Name):
            out.append(d.id)
        elif isinstance(d, ast.Attribute):
            # e.g., semantic_kernel.functions.kernel_function → kernel_function
            out.append(d.attr)
    return out


def _extract_kernel_function_meta(deco: ast.AST) -> dict[str, str | None]:
    """Return {name, description} if present in a kernel_function/skill_function decorator."""
    name: str | None = None
    desc: str | None = None

    if isinstance(deco, ast.Call):
        # kernel_function("mytool", description="...") or kernel_function(name="...")
        if isinstance(deco.func, ast.Name) and deco.func.id in _SK_DECORATORS:
            # positional first arg as name
            if deco.args:
                a0 = deco.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    name = a0.value
            for kw in deco.keywords or []:
                if (
                    kw.arg == "name"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    name = kw.value.value
                if (
                    kw.arg == "description"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    desc = kw.value.value
        elif isinstance(deco.func, ast.Attribute) and deco.func.attr in _SK_DECORATORS:
            # semantic_kernel.functions.kernel_function(...)
            if deco.args:
                a0 = deco.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    name = a0.value
            for kw in deco.keywords or []:
                if (
                    kw.arg == "name"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    name = kw.value.value
                if (
                    kw.arg == "description"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    desc = kw.value.value
    return {"name": name, "description": desc}


def _find_prompt_files(root: Path, limit: int = 50) -> list[Path]:
    """Search a few common prompt file names used by SK skills/plugins.
    Limits results to keep the detector fast.
    """
    results: list[Path] = []
    for pat in _PROMPT_FILE_PATTERNS:
        for p in root.rglob(f"**/*{pat}"):
            results.append(p)
            if len(results) >= limit:
                return results
    # Also scan for common folders
    for folder in ("plugins", "skills", "semantic_kernel_plugins", "semantic-kernel-plugins"):
        base = root / folder
        if base.exists():
            for p in base.rglob("*.txt"):
                results.append(p)
                if len(results) >= limit:
                    return results
    return results


def detect_path(source: str) -> DetectReport:
    root = Path(source).expanduser().resolve()
    files = _walk_py(root)
    rep = DetectReport(confidence=0.0, notes=[])

    if not files:
        return rep

    # First pass: collect SK hints quickly for confidence baseline
    sk_suspects: list[Path] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if _is_sk_file(text):
            sk_suspects.append(f)
            rep.notes.append(f"semantic-kernel usage hint in {f.name}")
            rep.confidence = max(rep.confidence, 0.4)

    # Second pass: AST parse for decorators and function schemas
    for f in sk_suspects or files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(text)
        except Exception:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                decs = _decorator_names(node)
                if any(d in _SK_DECORATORS for d in decs):
                    # Try to extract tool name/description from the exact decorator call
                    tool_name: str | None = None
                    tool_desc: str | None = None
                    for d in node.decorator_list:
                        meta = _extract_kernel_function_meta(d)
                        tool_name = tool_name or meta.get("name")
                        tool_desc = tool_desc or meta.get("description")

                    # Fall back to function name
                    tname = (tool_name or node.name).replace("_", "-")
                    schema = infer_schema_from_ast_func(node)
                    rep.tools.append(
                        {
                            "id": tname,
                            "name": tname,
                            "description": tool_desc or "",
                            "input_schema": schema,
                        }
                    )
                    rep.confidence = max(rep.confidence, 0.7)

        # If this file looks very SK-centric, add as resource pointer
        if f.name in {"plugins.py", "skills.py", "server.py"}:
            rep.resources.append(
                {
                    "id": f"{f.stem}-source",
                    "name": "server/skills source",
                    "type": "inline",
                    "uri": f"file://{f.name}",
                }
            )

    # Prompt/resource sweep (best-effort)
    prompts = _find_prompt_files(root)
    for p in prompts[:25]:  # cap
        rep.prompts.append(
            {
                "id": p.stem,
                "name": p.name,
                "uri": f"file://{p.as_posix()}",
            }
        )
    if prompts:
        rep.notes.append(f"found {len(prompts)} potential SK prompt files")
        rep.confidence = max(rep.confidence, 0.6)

    # Final signal
    if rep.tools:
        rep.notes.append(f"found {len(rep.tools)} tool(s) via Semantic Kernel decorators")
        rep.confidence = max(rep.confidence, 0.75)

    return rep
