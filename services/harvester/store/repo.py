from __future__ import annotations

import hashlib
from pathlib import Path

ARTIFACT_ROOT = Path("harvester_artifacts").resolve()


def _ext_for_kind(kind: str) -> str:
    k = (kind or "").lower()
    if k in {"manifest", "index", "sbom"}:
        return ".json"
    if k == "log":
        return ".log"
    return ".bin"


def put_artifact(job_id: str, kind: str, data: bytes) -> str:
    """Write artifact bytes to disk with content-hash name; return file:// URI."""
    h = hashlib.sha256(data).hexdigest()[:16]
    ext = _ext_for_kind(kind)
    out_dir = ARTIFACT_ROOT / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{h}_{kind}{ext}"
    path.write_bytes(data)
    return f"file://{path}"


def open_artifact(uri: str) -> bytes:
    assert uri.startswith("file://")
    path = Path(uri.replace("file://", "")).resolve()
    return path.read_bytes()


def manifest_link(uri: str) -> str:
    # For now, pass-through; later map to CDN/S3 links.
    return uri
