from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path


def _extract_existing(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    # Prefer canonical {"manifests": [...]} shape
    if isinstance(payload.get("manifests"), list):
        return [x for x in payload["manifests"] if isinstance(x, str)]
    # Tolerate alternative shapes sometimes seen in the wild
    if isinstance(payload.get("items"), list):
        out: list[str] = []
        for it in payload["items"]:
            if isinstance(it, str):
                out.append(it)
            elif isinstance(it, dict) and isinstance(it.get("manifest_url"), str):
                out.append(it["manifest_url"])
        return out
    return []


def write_index(path: str | Path, manifests: Iterable[str], *, additive: bool = True) -> Path:
    """Write an index.json that lists manifest paths/URLs.

    If additive=True and an index already exists, merge (dedupe, preserve order).
    Returns the absolute path written.
    """
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    new_items = [str(m).strip() for m in manifests if str(m).strip()]

    existing: list[str] = []
    if additive and p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            existing = _extract_existing(data)
        except Exception:
            existing = []

    merged: list[str] = []
    for item in [*existing, *new_items]:
        if item not in merged:
            merged.append(item)

    payload = {"manifests": merged}
    p.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return p


__all__ = ["write_index"]
