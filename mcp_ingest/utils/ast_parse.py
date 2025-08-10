from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "safe_parse",
    "parse_file",
    "iter_functions",
    "get_decorator_names",
    "ArgSpec",
    "function_args",
    "find_fastmcp_name",
    "find_tool_functions",
]


# ---- basic parsing ----


def safe_parse(src: str, *, filename: str = "<string>") -> ast.AST:
    """Parse Python source to AST without executing it.
    Tolerant to minor syntax quirks; raises SyntaxError if irrecoverable.
    """
    return ast.parse(src, filename=filename)


def parse_file(path: str | Path) -> ast.AST:
    p = Path(path).expanduser().resolve()
    return safe_parse(p.read_text(encoding="utf-8"), filename=str(p))


# ---- discovery helpers ----


def iter_functions(tree: ast.AST) -> Iterator[ast.FunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            yield node


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def get_decorator_names(fn: ast.FunctionDef) -> list[str]:
    names: list[str] = []
    for d in fn.decorator_list:
        names.append(_dotted_name(d))
    return [n for n in names if n]


@dataclass
class ArgSpec:
    name: str
    annotation: str | None = None
    has_default: bool = False


def _ann_to_str(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _dotted_name(node)
    if isinstance(node, ast.Subscript):
        return _dotted_name(node.value)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def function_args(fn: ast.FunctionDef) -> list[ArgSpec]:
    args: list[ArgSpec] = []

    posonly = list(getattr(fn.args, "posonlyargs", []) or [])
    regargs = list(fn.args.args or [])
    all_pos = posonly + regargs
    defaults = list(fn.args.defaults or [])
    offset = len(all_pos) - len(defaults)

    for i, a in enumerate(all_pos):
        if a.arg in {"self", "cls"}:
            continue
        ann = _ann_to_str(a.annotation)
        has_def = i >= offset
        args.append(ArgSpec(a.arg, ann, has_def))

    for i, a in enumerate(list(fn.args.kwonlyargs or [])):
        ann = _ann_to_str(a.annotation)
        has_def = bool((fn.args.kw_defaults or [None] * (i + 1))[i])
        args.append(ArgSpec(a.arg, ann, has_def))

    return args


def find_fastmcp_name(tree: ast.AST) -> str | None:
    """Return FastMCP(name=...) if present; otherwise None."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _dotted_name(node.func).endswith("FastMCP"):
            # name via first arg or kwarg
            if node.args:
                a0 = node.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    return a0.value
            for kw in getattr(node, "keywords", []) or []:
                if (
                    kw.arg == "name"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    return kw.value.value
    return None


def find_tool_functions(tree: ast.AST) -> list[ast.FunctionDef]:
    out: list[ast.FunctionDef] = []
    for fn in iter_functions(tree):
        decos = get_decorator_names(fn)
        if any(name.split(".")[-1] == "tool" for name in decos):
            out.append(fn)
    return out
