from __future__ import annotations

"""
Utilities to download and safely extract a GitHub repository archive for a given
ref (branch/tag/SHA) without performing a full `git clone`.

Primary entrypoint:

    download_ref(owner: str, repo: str, ref: str, dest_dir: str | Path) -> Path

This function attempts, in order:
  1) https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{ref}
  2) https://codeload.github.com/{owner}/{repo}/zip/refs/tags/{ref}
  3) https://codeload.github.com/{owner}/{repo}/zip/{ref}        (SHA or fallback)

It streams the ZIP with timeouts and a size cap, performs ZipSlip-safe extraction,
checks total uncompressed size, and returns the extracted *root* directory.

Configuration (env overrides):
  MCP_INGEST_MAX_ZIP_BYTES   -> default 200 MiB (for the downloaded ZIP and soft cap for uncompressed)
  MCP_INGEST_HTTP_TIMEOUT    -> default 30.0 seconds per request

Dependencies: standard library + httpx (already in project deps).
"""

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

import httpx

__all__ = ["download_ref", "ArchiveError"]

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
DEFAULT_MAX_ZIP_BYTES = int(os.getenv("MCP_INGEST_MAX_ZIP_BYTES", str(200 * 1024 * 1024)))  # 200MB
DEFAULT_HTTP_TIMEOUT = float(os.getenv("MCP_INGEST_HTTP_TIMEOUT", "30.0"))


class ArchiveError(RuntimeError):
    """Raised when downloading or extracting a GitHub archive fails safely."""


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def download_ref(owner: str, repo: str, ref: str, dest_dir: str | Path) -> Path:
    """Download a GitHub codeload ZIP for a specific ref and safely extract it.

    The function tries heads -> tags -> raw ref (SHA) endpoints. The ZIP is streamed
    with a size cap and extracted with ZipSlip guards. The returned path is the
    *extracted root folder* (usually ``{repo}-{ref}``), suitable as a local working
    directory for subsequent detection/harvest steps.

    Args:
        owner: GitHub organization/user (e.g., "modelcontextprotocol").
        repo: Repository name (e.g., "servers").
        ref:  Branch/tag/commit SHA.
        dest_dir: Destination directory where a temp workspace will be created.

    Returns:
        Path to the extracted root directory.

    Raises:
        ArchiveError: on download/extraction failures or safety violations.
    """
    if not owner or not repo or not ref:
        raise ArchiveError("owner, repo, and ref are required")

    dest = Path(dest_dir).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)

    # Unique workspace under the destination (cleaned on success/failure)
    work = Path(tempfile.mkdtemp(prefix=f"gharch-{owner}-{repo}-", dir=str(dest)))
    zip_path = work / f"{repo}-{_safe_ref_for_name(ref)}.zip"
    extract_dir = work / "extract"
    extract_dir.mkdir(parents=True, exist_ok=True)

    # Candidate codeload endpoints (most likely first)
    ref_q = quote(ref, safe="")  # encode slashes etc.
    endpoints = [
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{ref_q}",
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/tags/{ref_q}",
        f"https://codeload.github.com/{owner}/{repo}/zip/{ref_q}",
    ]

    ok = False
    last_err: str | None = None
    for url in endpoints:
        try:
            _stream_download(url, zip_path, max_bytes=DEFAULT_MAX_ZIP_BYTES)
            ok = True
            break
        except ArchiveError as e:
            # Keep trying other endpoints; record the last error
            last_err = str(e)
            continue
    if not ok:
        # Clean workspace on failure
        shutil.rmtree(work, ignore_errors=True)
        raise ArchiveError(last_err or "failed to download archive")

    try:
        root = _safe_extract_zip(zip_path, extract_dir, max_uncompressed=DEFAULT_MAX_ZIP_BYTES)
        # The codeload zip typically extracts to a single top-level directory
        root = _strip_singleton_dir(root)
        return root
    except Exception as e:
        shutil.rmtree(work, ignore_errors=True)
        raise ArchiveError(f"extraction failed: {e}") from e


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _safe_ref_for_name(ref: str) -> str:
    # Accept only filesystem-friendly subset for naming the .zip file
    safe = [c if c.isalnum() or c in ("-", "_", ".") else "-" for c in ref]
    return "".join(safe).strip("-_") or "ref"


def _stream_download(url: str, out_path: Path, *, max_bytes: int) -> None:
    """Stream a URL to disk with a size cap & timeouts; errors on 4xx/5xx or oversize."""
    total = 0
    with httpx.stream("GET", url, timeout=DEFAULT_HTTP_TIMEOUT, follow_redirects=True) as resp:
        if resp.status_code == 404:
            raise ArchiveError(f"not found: {url}")
        if resp.status_code >= 400:
            raise ArchiveError(f"download error {resp.status_code} for {url}")
        cl = resp.headers.get("Content-Length")
        if cl is not None:
            try:
                if int(cl) > max_bytes:
                    raise ArchiveError(f"zip too large (Content-Length {cl} > {max_bytes})")
            except ValueError:
                pass
        with open(out_path, "wb") as f:
            for chunk in resp.iter_bytes():
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ArchiveError(f"zip exceeds max size ({total} > {max_bytes} bytes)")
                f.write(chunk)


def _safe_extract_zip(zip_path: Path, dest: Path, *, max_uncompressed: int) -> Path:
    """Extract zip into *dest* safely (ZipSlip guard), with a soft uncompressed size cap.
    Returns the top-level extraction path (dest).
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            # Size guard to avoid zip bombs
            total_uncompressed = 0
            for info in zf.infolist():
                total_uncompressed += info.file_size
                if total_uncompressed > max_uncompressed:
                    raise ArchiveError(
                        f"zip uncompressed content too large (> {max_uncompressed} bytes)"
                    )
                _assert_safe_member(info.filename)

            # Extract with path normalization and traversal checks
            for info in zf.infolist():
                target = (dest / _sanitize_member(info.filename)).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    raise ArchiveError("unsafe zip entry path traversal detected")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info, "r") as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        return dest
    except zipfile.BadZipFile as e:
        raise ArchiveError(f"invalid zip: {zip_path}") from e


def _assert_safe_member(name: str) -> None:
    # Reject absolute paths and parent traversal
    if name.startswith(("/", "\\")):
        raise ArchiveError(f"unsafe zip entry (absolute): {name}")
    parts = Path(name).as_posix().split("/")
    if any(p == ".." for p in parts):
        raise ArchiveError(f"unsafe zip entry (parent traversal): {name}")


def _sanitize_member(name: str) -> Path:
    # Convert to safe relative path under the extraction directory
    parts = [p for p in Path(name).parts if p not in ("", ".", "..")]
    return Path(*parts)


def _strip_singleton_dir(extracted_root: Path) -> Path:
    """If the extracted tree has a single top-level directory, return it; else return root."""
    try:
        entries = [p for p in extracted_root.iterdir()]
    except FileNotFoundError:
        return extracted_root
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extracted_root


if __name__ == "__main__":  # pragma: no cover - ad hoc test helper
    import argparse

    ap = argparse.ArgumentParser(description="Download + extract a GitHub ref (heads/tags/sha)")
    ap.add_argument("owner")
    ap.add_argument("repo")
    ap.add_argument("ref")
    ap.add_argument("dest", nargs="?", default=".")
    ns = ap.parse_args()

    root = download_ref(ns.owner, ns.repo, ns.ref, ns.dest)
    print(root)
