from __future__ import annotations

"""
Unified fetch/prepare entrypoint for repo sources.

Supported inputs:
  • Local directory: /path/to/repo or ./repo
  • Git URL:         https://github.com/org/repo.git[@ref] | git@github.com:org/repo.git[@ref]
  • ZIP URL:         https://.../repo.zip  (or file:///.../repo.zip)

Returns a LocalSource containing a local working directory and a cleanup() hook.

Notes:
  - ZIP: streamed download with timeouts & size guards; ZipSlip-safe extraction.
  - GIT: shallow clone (depth=1) unless an explicit @ref/sha is provided.
  - Cleanup is idempotent; local directories are never removed.
"""

import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

import httpx

__all__ = ["LocalSource", "prepare_source", "FetchError"]

# ----------------------------
# Config (env-overridable)
# ----------------------------
DEFAULT_MAX_ZIP_BYTES = int(os.getenv("MCP_INGEST_MAX_ZIP_BYTES", str(200 * 1024 * 1024)))  # 200MB
DEFAULT_HTTP_TIMEOUT = float(os.getenv("MCP_INGEST_HTTP_TIMEOUT", "30.0"))  # seconds


class FetchError(RuntimeError):
    """Raised when a source cannot be prepared safely."""


@dataclass
class LocalSource:
    kind: Literal["dir", "git", "zip"]
    path: Path  # absolute path to the prepared source folder
    origin: str  # original user-provided source string
    cleanup: Callable[[], None]  # idempotent cleanup
    sha: str | None = None  # git commit (if applicable)
    repo_name: str | None = None  # inferred name for tagging


# ----------------------------
# Public API
# ----------------------------


def prepare_source(source: str, *, workdir: str | Path | None = None) -> LocalSource:
    """
    Prepare a local working copy of a source (dir | git | zip).
    Returns a LocalSource with a cleanup() hook.

    Examples:
      prepare_source("./servers")
      prepare_source("https://github.com/org/repo.git@main")
      prepare_source("https://github.com/org/repo/archive/refs/heads/main.zip")
      prepare_source("file:///tmp/repo.zip")
    """
    src = source.strip()
    if not src:
        raise FetchError("empty source")

    # NOTE: _classify_source may return (kind, ref) OR (kind, ref, normalized_src)
    classified = _classify_source(src)
    if isinstance(classified, tuple) and len(classified) == 3:
        kind, ref, normalized = classified
        src = normalized
    else:
        kind, ref = classified  # type: ignore[misc]

    # Ensure base working directory
    base = Path(workdir).expanduser().resolve() if workdir else None

    if kind == "zip":
        return _prepare_from_zip(src, base)
    if kind == "git":
        return _prepare_from_git(src, ref, base)
    if kind == "dir":
        return _prepare_from_dir(src)

    raise FetchError(f"unsupported source: {src}")


# ----------------------------
# Classification
# ----------------------------

_GIT_RE = re.compile(r"(?i)\.git(?:@(?P<ref>[\w\.-/]+))?$")
_SCP_GIT_RE = re.compile(r"^[\w\-]+@[\w\.-]+:.*\.git(?:@(?P<ref>[\w\.-/]+))?$")
_ZIP_RE = re.compile(r"(?i)\.zip$")

# Recognize GitHub HTTPS repo URLs, optionally /tree/<ref>[/<subpath>]
_GH_RE = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+)"
    r"(?:/)?(?:tree/(?P<ref>[^/]+)(?:/(?P<subpath>.*))?)?$",
    re.IGNORECASE,
)


def _normalize_github_http_to_git(src: str) -> tuple[str, str | None] | None:
    """
    If src is a GitHub HTTPS repo URL, return (normalized_git_url, ref).
    Examples:
      https://github.com/owner/repo           -> (https://github.com/owner/repo.git, None)
      https://github.com/owner/repo/tree/main -> (https://github.com/owner/repo.git, "main")
    """
    m = _GH_RE.match(src)
    if not m:
        return None
    owner, repo, ref = m.group("owner"), m.group("repo"), m.group("ref")
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"https://github.com/{owner}/{repo}.git", ref


def _classify_source(
    source: str,
) -> tuple[Literal["dir", "git", "zip"], str | None] | tuple[Literal["git"], str | None, str]:
    """Return (kind, ref) OR (kind, ref, normalized_src). Ref may be branch/tag/sha for git."""
    parsed = urlparse(source)

    # ZIP (http/https/file) by suffix
    if parsed.scheme in {"http", "https", "file"} and _ZIP_RE.search(parsed.path or ""):
        return "zip", None

    # GIT scp-style or explicit .git
    if _SCP_GIT_RE.match(source):
        ref = _extract_ref(source)
        return "git", ref

    if (
        parsed.scheme in {"http", "https", "ssh", "git"}
        or source.endswith(".git")
        or ".git@" in source
    ):
        if ".git" in source:
            ref = _extract_ref(source)
            return "git", ref

    # GitHub HTTPS repo URLs without .git (and optional /tree/<ref>)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() == "github.com":
        norm = _normalize_github_http_to_git(source)
        if norm:
            git_url, ref = norm
            return "git", ref, git_url

    # Otherwise treat as directory
    return "dir", None


def _extract_ref(source: str) -> str | None:
    """Parse @ref from the tail of a git-like string."""
    m = _GIT_RE.search(source)
    if not m:
        m = _SCP_GIT_RE.search(source)
    if m:
        return m.groupdict().get("ref")
    # fallback: if we see '@' after '.git', grab the suffix
    if ".git@" in source:
        return source.split(".git@", 1)[1].strip() or None
    return None


# ----------------------------
# ZIP handling
# ----------------------------


def _prepare_from_zip(url_or_file: str, base: Path | None) -> LocalSource:
    # Create temp workspace
    tmp_root = Path(tempfile.mkdtemp(prefix="mcpzip-")) if base is None else base
    created_tmp = base is None

    try:
        zip_path = _download_zip_if_needed(url_or_file, dest_dir=tmp_root)
        extract_dir = tmp_root / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)

        root = _safe_extract_zip(zip_path, extract_dir, max_uncompressed=DEFAULT_MAX_ZIP_BYTES)
        repo_root = _strip_singleton_dir(root)

        repo_name = repo_root.name
        path = repo_root.resolve()

        def cleanup() -> None:
            if created_tmp:
                shutil.rmtree(tmp_root, ignore_errors=True)

        return LocalSource(
            kind="zip",
            path=path,
            origin=url_or_file,
            cleanup=cleanup,
            sha=None,
            repo_name=repo_name,
        )
    except Exception as e:
        # cleanup on failure
        if base is None:
            shutil.rmtree(tmp_root, ignore_errors=True)
        raise _as_fetch_error(e, f"failed to prepare zip: {url_or_file}") from e


def _download_zip_if_needed(url_or_file: str, dest_dir: Path) -> Path:
    parsed = urlparse(url_or_file)
    if parsed.scheme == "file":
        p = Path(unquote(parsed.path)).expanduser().resolve()
        if not p.exists():
            raise FetchError(f"zip not found: {p}")
        if not _ZIP_RE.search(p.name):
            raise FetchError(f"not a .zip file: {p}")
        return p

    if parsed.scheme in {"http", "https"}:
        filename = Path(parsed.path).name or "repo.zip"
        if not _ZIP_RE.search(filename):
            filename += ".zip"
        out = dest_dir / filename
        _stream_download(url_or_file, out, max_bytes=DEFAULT_MAX_ZIP_BYTES)
        return out

    # plain path?
    p = Path(url_or_file).expanduser().resolve()
    if p.exists() and _ZIP_RE.search(p.name):
        return p

    raise FetchError(f"unsupported zip scheme: {url_or_file}")


def _stream_download(url: str, out_path: Path, *, max_bytes: int) -> None:
    """Stream a URL to disk with a size cap & timeouts."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with httpx.stream("GET", url, timeout=DEFAULT_HTTP_TIMEOUT, follow_redirects=True) as resp:
        if resp.status_code >= 400:
            raise FetchError(f"download error {resp.status_code} for {url}")
        cl = resp.headers.get("Content-Length")
        if cl is not None:
            try:
                if int(cl) > max_bytes:
                    raise FetchError(f"zip too large (Content-Length {cl} > {max_bytes})")
            except ValueError:
                pass
        with open(out_path, "wb") as f:
            for chunk in resp.iter_bytes():
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise FetchError(f"zip exceeds max size ({total} > {max_bytes} bytes)")
                f.write(chunk)


def _safe_extract_zip(zip_path: Path, dest: Path, *, max_uncompressed: int) -> Path:
    """Extract zip into dest safely (no ZipSlip), with a soft uncompressed size cap.
    Returns the top-level extraction path (dest).
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            # Size guard to avoid zip bombs
            total_uncompressed = 0
            for info in zf.infolist():
                total_uncompressed += info.file_size
                if total_uncompressed > max_uncompressed:
                    raise FetchError(
                        f"zip uncompressed content too large (> {max_uncompressed} bytes)"
                    )

                # Path traversal guard
                _assert_safe_member(info.filename)

            # Extract manually with checks
            for info in zf.infolist():
                # Normalize target path under dest
                target = (dest / _sanitize_zip_member(info.filename)).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    raise FetchError("unsafe zip entry path traversal detected")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info, "r") as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        return dest
    except zipfile.BadZipFile as e:
        raise FetchError(f"invalid zip: {zip_path}") from e


def _assert_safe_member(name: str) -> None:
    # Reject absolute paths and parent traversal
    if name.startswith(("/", "\\")):
        raise FetchError(f"unsafe zip entry (absolute): {name}")
    norm = Path(name).as_posix()
    if ".." in Path(norm).parts:
        raise FetchError(f"unsafe zip entry (parent traversal): {name}")


def _sanitize_zip_member(name: str) -> Path:
    # Convert to safe relative path
    p = Path(name)
    parts = [part for part in p.parts if part not in ("", ".", "..")]
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


# ----------------------------
# Git handling
# ----------------------------


def _prepare_from_git(url: str, ref: str | None, base: Path | None) -> LocalSource:
    tmp_root = Path(tempfile.mkdtemp(prefix="mcpgit-")) if base is None else base
    created_tmp = base is None
    repo_dir = tmp_root / "repo"

    try:
        sha = _git_clone(url, repo_dir, ref=ref)
        name = _infer_repo_name(url)
        path = repo_dir.resolve()

        def cleanup() -> None:
            if created_tmp:
                shutil.rmtree(tmp_root, ignore_errors=True)

        return LocalSource(
            kind="git", path=path, origin=url, cleanup=cleanup, sha=sha, repo_name=name
        )
    except Exception as e:
        if base is None:
            shutil.rmtree(tmp_root, ignore_errors=True)
        # Chain the original exception to preserve its traceback
        raise _as_fetch_error(e, f"failed to prepare git repo: {url}") from e


def _git_clone(url: str, dest: Path, *, ref: str | None) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # If ref provided, attempt shallow fetch of that ref; otherwise shallow clone
    try:
        if ref:
            # Clone without checkout, then fetch specific ref shallowly
            _run(["git", "init"], cwd=dest)
            _run(["git", "remote", "add", "origin", url], cwd=dest)
            _run(["git", "fetch", "--depth", "1", "origin", ref], cwd=dest)
            _run(["git", "checkout", "FETCH_HEAD"], cwd=dest)
        else:
            _run(["git", "clone", "--depth", "1", url, str(dest)])
        # Ensure we have a HEAD SHA
        sha = _run(["git", "rev-parse", "HEAD"], cwd=dest).stdout.strip()
        return sha
    except subprocess.CalledProcessError as e:
        raise FetchError(f"git error: {e.stderr.strip() or e.stdout.strip()}") from e


def _infer_repo_name(url: str) -> str:
    # Extract the repo name from the URL (strip .git and @ref)
    tail = url.rstrip("/").split("/")[-1]
    if ".git" in tail:
        tail = tail.split(".git", 1)[0]
    if "@" in tail:
        tail = tail.split("@", 1)[0]
    return tail or "repo"


def _run(cmd, *, cwd: Path | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


# ----------------------------
# Directory handling
# ----------------------------


def _prepare_from_dir(path_str: str) -> LocalSource:
    p = Path(path_str).expanduser().resolve()
    if not p.exists() or not p.is_dir():
        raise FetchError(f"directory not found: {p}")

    name = p.name

    def cleanup() -> None:
        # No-op for local directories
        return None

    return LocalSource(kind="dir", path=p, origin=str(p), cleanup=cleanup, sha=None, repo_name=name)


# ----------------------------
# Helpers
# ----------------------------


def _as_fetch_error(exc: Exception, ctx: str) -> FetchError:
    if isinstance(exc, FetchError):
        return exc
    return FetchError(f"{ctx}: {exc}")
