from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:  # optional
    import boto3  # type: ignore
except Exception:  # pragma: no cover
    boto3 = None  # type: ignore

__all__ = [
    "PublishResult",
    "publish",
    "update_global_index",
    "merge_indexes",
]


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------


@dataclass
class PublishResult:
    provider: str
    destination: str
    objects: dict[str, str]  # key -> final URL or path
    ok: bool
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _ensure_listable_paths(paths: dict[str, str | Path]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for k, v in paths.items():
        p = Path(str(v)).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"publish: missing path for {k}: {p}")
        out[k] = p
    return out


def _guess_mime(name: str) -> str:
    if name.endswith(".json"):
        return "application/json"
    if name.endswith(".yaml") or name.endswith(".yml"):
        return "application/x-yaml"
    return "application/octet-stream"


def _run(cmd: Sequence[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{p.stderr}")


# -----------------------------------------------------------------------------
# Providers
# -----------------------------------------------------------------------------


# S3 provider (boto3 preferred; fallback to aws CLI)


def _publish_s3(
    paths: dict[str, Path], dest: str, *, cache_control: str, content_hash: bool
) -> PublishResult:
    # dest example: s3://my-bucket/prefix/
    if not dest.startswith("s3://"):
        return PublishResult("s3", dest, {}, False, error="dest must start with s3://bucket/")

    bucket_and_prefix = dest[len("s3://") :]
    if "/" in bucket_and_prefix:
        bucket, prefix = bucket_and_prefix.split("/", 1)
        if prefix and not prefix.endswith("/"):
            prefix += "/"
    else:
        bucket, prefix = bucket_and_prefix, ""

    published: dict[str, str] = {}

    def _object_key(name: str, p: Path) -> str:
        if content_hash:
            h = _sha256_file(p)[:16]
            base = p.name
            return f"{prefix}{h}-{base}"
        return f"{prefix}{p.name}"

    # boto3 path
    if boto3 is not None:
        try:
            s3 = boto3.client("s3")
            for k, p in paths.items():
                key = _object_key(k, p)
                extra = {"CacheControl": cache_control, "ContentType": _guess_mime(p.name)}
                s3.upload_file(str(p), bucket, key, ExtraArgs=extra)
                published[k] = f"https://{bucket}.s3.amazonaws.com/{key}"
            return PublishResult("s3", dest, published, True)
        except Exception as e:  # pragma: no cover
            return PublishResult("s3", dest, published, False, error=str(e))

    # fallback to AWS CLI
    if shutil.which("aws"):
        try:
            for k, p in paths.items():
                key = _object_key(k, p)
                url = f"s3://{bucket}/{key}"
                # set cache-control and content-type if possible
                cmd = [
                    "aws",
                    "s3",
                    "cp",
                    str(p),
                    url,
                    "--cache-control",
                    cache_control,
                    "--content-type",
                    _guess_mime(p.name),
                ]
                _run(cmd)
                published[k] = f"https://{bucket}.s3.amazonaws.com/{key}"
            return PublishResult("s3", dest, published, True)
        except Exception as e:  # pragma: no cover
            return PublishResult("s3", dest, published, False, error=str(e))

    return PublishResult("s3", dest, {}, False, error="boto3 or aws CLI required for S3 publishing")


# GH Pages provider (treat dest as local folder; caller pushes via git/CI)


def _publish_ghpages(
    paths: dict[str, Path], dest: str, *, cache_control: str, content_hash: bool
) -> PublishResult:
    # dest example: ./public or ../docs (a folder tracked by GitHub Pages)
    target = Path(dest).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    published: dict[str, str] = {}

    for k, p in paths.items():
        if content_hash:
            h = _sha256_file(p)[:16]
            out = target / f"{h}-{p.name}"
        else:
            out = target / p.name
        if out.resolve() != p.resolve():
            shutil.copy2(p, out)
        # URL path is repo-dependent; we return relative path
        published[k] = str(out)

    # Cache control must be handled by hosting config; we only copy files
    return PublishResult("ghpages", dest, published, True)


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def publish(
    paths: dict[str, str | Path],
    dest: str,
    *,
    provider: str = "s3",
    cache_control: str = "public,max-age=31536000",
    content_hash: bool = True,
) -> PublishResult:
    """Publish artifacts (manifest.json, index.json, etc.) to a target provider.

    Returns PublishResult with mapping of logical keys -> final URLs/paths.
    Idempotent when content_hash=True.
    """
    norm = _ensure_listable_paths(paths)
    if provider == "s3":
        return _publish_s3(norm, dest, cache_control=cache_control, content_hash=content_hash)
    if provider in {"ghpages", "gh", "local"}:
        return _publish_ghpages(norm, dest, cache_control=cache_control, content_hash=content_hash)
    return PublishResult(provider, dest, {}, False, error=f"unknown provider: {provider}")


def update_global_index(
    manifests: list[str], shard_key: str, *, out_dir: str | Path = "global-index"
) -> None:
    """Write (or update) a sharded global index file locally.

    Shape: out_dir/index-<shard_key>.json with {"manifests": [...]} (deduped).
    Caller can then publish this folder using `publish(..., provider=ghpages|s3)`.
    """
    odir = Path(out_dir).expanduser().resolve()
    odir.mkdir(parents=True, exist_ok=True)
    shard = odir / f"index-{shard_key}.json"

    existing: list[str] = []
    if shard.exists():
        try:
            data = json.loads(shard.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("manifests"), list):
                existing = [str(x) for x in data["manifests"] if isinstance(x, str)]
        except Exception:  # pragma: no cover
            existing = []

    merged: list[str] = []
    for x in [*existing, *manifests]:
        if x not in merged:
            merged.append(x)

    shard.write_text(json.dumps({"manifests": merged}, indent=2, sort_keys=True), encoding="utf-8")


# -----------------------------------------------------------------------------
# Repo-level merge utility
# -----------------------------------------------------------------------------


def _extract_from_index_payload(payload: Any, base: Path | None) -> list[str]:
    """Extract manifest entries from an index-like payload.

    Supports common shapes and resolves relative paths against *base* (if provided).
    """
    out: list[str] = []
    if not isinstance(payload, dict):
        return out

    items: list[str] = []
    if isinstance(payload.get("manifests"), list):
        items = [x for x in payload["manifests"] if isinstance(x, str)]
    elif isinstance(payload.get("items"), list):
        for it in payload["items"]:
            if isinstance(it, str):
                items.append(it)
            elif isinstance(it, dict) and isinstance(it.get("manifest_url"), str):
                items.append(it["manifest_url"])

    # Resolve relative paths when base is a local filesystem path
    for i in items:
        s = i.strip()
        if not s:
            continue
        if s.startswith("http://") or s.startswith("https://") or s.startswith("s3://"):
            out.append(s)
        else:
            if base is not None:
                out.append(str((base / s).resolve()))
            else:
                out.append(s)
    return out


def merge_indexes(child_index_paths: Iterable[str | Path]) -> dict[str, Any]:
    """Merge multiple *local* child index.json files into a single repo-level index.

    Relative manifest entries are resolved against the directory of the child index file.
    Duplicates are removed while preserving first-seen order.

    Parameters
    ----------
    child_index_paths : Iterable[Union[str, Path]]
        Paths to child index.json files (local filesystem). URLs are tolerated
        but left as-is (no fetching in this helper).

    Returns
    -------
    Dict[str, Any]
        A dict with shape {"manifests": [ ... ]} suitable to write as index.json.
    """
    merged: list[str] = []

    for p in child_index_paths:
        ipath = Path(str(p)).expanduser()
        base_dir: Path | None = None
        data: dict[str, Any] | None = None

        # Only local files are read. If it looks like a URL, skip reading and just add it.
        s = str(p)
        if s.startswith("http://") or s.startswith("https://") or s.startswith("s3://"):
            # treat it directly as a manifest index URL (not typical for repo-level merge)
            # We cannot dereference here; skip.
            continue

        if ipath.exists():
            try:
                base_dir = ipath.parent.resolve()
                data = json.loads(ipath.read_text(encoding="utf-8"))
            except Exception:
                data = None
        if not data:
            continue

        manifests = _extract_from_index_payload(data, base=base_dir)
        for m in manifests:
            if m not in merged:
                merged.append(m)

    return {"manifests": merged}
