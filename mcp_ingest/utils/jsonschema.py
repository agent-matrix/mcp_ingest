from __future__ import annotations

import ast
from typing import Any

# Very light, best-effort schema inference from Python AST function signatures.

BASIC_MAP = {
    "str": {"type": "string"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "bool": {"type": "boolean"},
}


def _ann_to_schema(node: ast.AST | None) -> dict[str, Any]:
    if node is None:
        return {"type": "string"}
    # Name: str/int/bool/float
    if isinstance(node, ast.Name) and node.id in BASIC_MAP:
        return dict(BASIC_MAP[node.id])
    # Subscript like Optional[str], list[str]
    if isinstance(node, ast.Subscript):
        # Optional[T] -> T | null (approximate)
        base = getattr(node.value, "id", getattr(node.value, "attr", ""))
        if base in ("Optional", "Union"):
            return {"anyOf": [{"type": "string"}, {"type": "null"}]}
        if base in ("List", "list"):
            return {"type": "array", "items": {"type": "string"}}
    # Attribute like typing.List
    if isinstance(node, ast.Attribute) and node.attr in BASIC_MAP:
        return dict(BASIC_MAP[node.attr])
    return {"type": "string"}


def infer_schema_from_ast_func(fn: ast.FunctionDef) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []

    # Positional-only & regular args
    all_args = list(getattr(fn.args, "posonlyargs", [])) + list(fn.args.args)
    defaults = list(fn.args.defaults or [])
    # align defaults with args (defaults apply to last N args)
    default_offset = len(all_args) - len(defaults)

    for i, a in enumerate(all_args):
        if a.arg in ("self", "cls"):
            continue
        props[a.arg] = _ann_to_schema(a.annotation)
        if i >= default_offset:
            # has default
            pass
        else:
            required.append(a.arg)

    # kw-only args
    for i, a in enumerate(fn.args.kwonlyargs or []):
        props[a.arg] = _ann_to_schema(a.annotation)
        if not (fn.args.kw_defaults or [])[i]:
            required.append(a.arg)

    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = sorted(required)
    return schema


def merge_schemas(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge of two object schemas (best-effort)."""
    if not a:
        return dict(b)
    if not b:
        return dict(a)
    out = {**a}
    if a.get("type") == "object" and b.get("type") == "object":
        props = {**(a.get("properties") or {})}
        props.update(b.get("properties") or {})
        out["properties"] = props
        ra = set(a.get("required") or [])
        rb = set(b.get("required") or [])
        req = sorted(ra.union(rb))
        if req:
            out["required"] = req
    return out


__all__ = ["infer_schema_from_ast_func", "merge_schemas"]
