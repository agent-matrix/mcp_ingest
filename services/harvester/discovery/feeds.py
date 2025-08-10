from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # type: ignore


def load_feeds(path: str | Path) -> list[str]:
    """Load curated JSON/YAML list of sources (git URLs, manifest URLs, folders)."""
    p = Path(path).expanduser().resolve()
    text = p.read_text(encoding="utf-8")
    data: Any
    if p.suffix.lower() in {".yaml", ".yml"} and yaml:
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if isinstance(data, list):
        return [str(x) for x in data]
    if isinstance(data, dict) and isinstance(data.get("sources"), list):
        return [str(x) for x in data["sources"]]
    return []
