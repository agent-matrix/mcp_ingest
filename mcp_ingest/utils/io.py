from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore


def read_text(path: str | Path) -> str:
    p = Path(path).expanduser().resolve()
    return p.read_text(encoding="utf-8")


def read_json_or_yaml(path: str | Path) -> dict[str, Any]:
    text = read_text(path)
    # try yaml first if available, then json
    if yaml is not None:
        try:
            data = yaml.safe_load(text)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return json.loads(text)


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


__all__ = ["read_text", "read_json_or_yaml", "write_json"]
