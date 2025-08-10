from __future__ import annotations

"""Lightweight git utilities with a safe ZIP fallback (GitHub only).

Public API
----------
clone_shallow(url, dest, ref=None, *, timeout=600) -> str
    Shallow-clone `url` into directory `dest` and return the resolved commit SHA.
    If `git` is unavailable or the clone fails, and the host is GitHub, fall back to
    downloading a repository archive as ZIP (best-effort). In ZIP fallback mode, the
    exact commit SHA may be unknown; the function returns an empty string in that case.

Design notes
------------
• Safe subprocess execution with timeouts and clear error messages.
• ZIP fallback protects against ZipSlip and oversized downloads.
• Handles ref heuristics: branch/tag/commit SHA. When a commit SHA is given, uses
  `git fetch --depth 1 origin <sha>` to avoid fetching the full history.

This module is dependency-light and compatible with MatrixHub tooling.
"""

import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path

try:  # optional; used for ZIP fallback
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

import zipfile

__all__ = [
    "GitError",
    "clone_shallow",
]


class GitError(RuntimeError):
    """Raised when git operations fail in a non-transient way."""


_HEX_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def _is_commit(ref: str | None) -> bool:
    return bool(ref and _HEX_RE.match(ref))


def _run_git(
    args: Iterable[str], *, cwd: Path | None = None, timeout: int = 600
) -> subprocess.CompletedProcess:
    if shutil.which("git") is None:
        raise GitError("git is not installed or not in PATH")
    try:
        proc = subprocess.run(
            ["git", *list(args)],
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc
    except subprocess.TimeoutExpired as te:  # pragma: no cover
        raise GitError(f"git command timed out: {' '.join(args)}") from te


def _ensure_empty_dir(dest: Path) -> None:
    if dest.exists():
        # allow empty dir; otherwise fail
        if dest.is_file():
            raise GitError(f"destination is a file: {dest}")
        try:
            next(dest.iterdir())
            raise GitError(f"destination directory is not empty: {dest}")
        except StopIteration:
            return
    else:
        dest.mkdir(parents=True, exist_ok=True)


def _github_owner_repo(url: str) -> tuple[str, str] | None:
    """Parse GitHub owner/repo from clone URL.

    Supports HTTPS URLs like:
      https://github.com/owner/repo.git
      https://github.com/owner/repo
    and git+ssh is not supported for ZIP fallback.
    """
    m = re.match(r"^https?://(?:www\.)?github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/|$)", url)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    return owner, repo


def _zip_fallback(
    url: str, dest: Path, ref: str | None, *, timeout: int = 600, max_mb: int = 500
) -> str:
    """Download and extract a GitHub ZIP archive into `dest`.

    Returns "" (empty string) as SHA when the exact commit is unknown.
    """
    if httpx is None:
        raise GitError("ZIP fallback requires httpx; please install httpx or git")

    parsed = _github_owner_repo(url)
    if not parsed:
        raise GitError("ZIP fallback only supports https://github.com/<owner>/<repo> URLs")
    owner, repo = parsed

    # Try candidates for archive ref
    candidates: list[str] = []
    if ref:
        candidates.extend([ref, f"refs/heads/{ref}", f"refs/tags/{ref}"])
    else:
        candidates.extend(["HEAD", "refs/heads/main", "refs/heads/master"])  # best-effort

    last_err: Exception | None = None
    with tempfile.TemporaryDirectory(prefix="mcp_zip_") as tmpdir:
        tmp = Path(tmpdir)
        for cand in candidates:
            try:
                archive_url = f"https://codeload.github.com/{owner}/{repo}/zip/{cand}"
                zip_path = tmp / "repo.zip"
                # stream download with size guard
                total = 0
                max_bytes = max_mb * 1024 * 1024
                with httpx.stream("GET", archive_url, timeout=timeout) as r:
                    if r.status_code >= 400:
                        raise GitError(f"archive fetch failed ({r.status_code}) for ref '{cand}'")
                    with zip_path.open("wb") as f:
                        for chunk in r.iter_bytes():
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > max_bytes:
                                raise GitError("archive too large; aborting")
                            f.write(chunk)

                # Extract safely
                with zipfile.ZipFile(zip_path) as zf:
                    _safe_extract_zip(zf, tmp / "extract")

                # Move inner folder contents into dest
                extracted_root = _single_top_level_dir(tmp / "extract") or (tmp / "extract")
                for p in extracted_root.iterdir():
                    target = dest / p.name
                    if p.is_dir():
                        shutil.move(str(p), str(target))
                    else:
                        shutil.move(str(p), str(target))

                return (
                    ""  # SHA unknown in fallback (could be captured from file list, but optional)
                )
            except Exception as e:  # try next candidate
                last_err = e
                continue
    raise GitError(str(last_err) if last_err else "unknown ZIP fallback error")


def _safe_extract_zip(zf: zipfile.ZipFile, extract_to: Path) -> None:
    extract_to.mkdir(parents=True, exist_ok=True)
    for member in zf.infolist():
        # ZipSlip protection
        name = member.filename
        if name.startswith("/"):
            raise GitError("archive contains absolute paths; refusing to extract")
        # Normalize
        resolved = (extract_to / name).resolve()
        if not str(resolved).startswith(str(extract_to.resolve())):
            raise GitError("archive contains path traversal; refusing to extract")
        if member.is_dir():
            resolved.mkdir(parents=True, exist_ok=True)
        else:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member, "r") as src, open(resolved, "wb") as dst:
                shutil.copyfileobj(src, dst)


def _single_top_level_dir(root: Path) -> Path | None:
    entries = [p for p in root.iterdir() if not p.name.startswith(".__MACOSX")]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return None


def clone_shallow(url: str, dest: str | Path, ref: str | None = None, *, timeout: int = 600) -> str:
    """Shallow clone a repository into `dest` and return the commit SHA.

    If `git` is missing or the clone fails and the URL is a GitHub repo, attempt ZIP fallback.
    In fallback mode, the returned SHA may be an empty string when not determinable.
    """
    url = url.strip()
    dest_path = Path(dest).expanduser().resolve()
    _ensure_empty_dir(dest_path)

    try:
        # Fast path when git is present
        if _is_commit(ref):
            # Commit SHA flow: init + fetch that SHA shallowly
            proc = _run_git(["init"], cwd=dest_path, timeout=timeout)
            if proc.returncode != 0:
                raise GitError(proc.stderr.strip() or "git init failed")
            proc = _run_git(["remote", "add", "origin", url], cwd=dest_path, timeout=timeout)
            if proc.returncode != 0:
                raise GitError(proc.stderr.strip() or "git remote add failed")
            proc = _run_git(
                ["fetch", "--depth", "1", "origin", ref], cwd=dest_path, timeout=timeout
            )
            if proc.returncode != 0:
                raise GitError(proc.stderr.strip() or f"git fetch failed for {ref}")
            proc = _run_git(["checkout", "FETCH_HEAD"], cwd=dest_path, timeout=timeout)
            if proc.returncode != 0:
                raise GitError(proc.stderr.strip() or "git checkout FETCH_HEAD failed")
        else:
            # Branch/tag or None
            clone_args = ["clone", "--depth", "1"]
            if ref:
                clone_args += ["--branch", ref]
            clone_args += [url, str(dest_path)]
            proc = _run_git(clone_args, timeout=timeout)
            if proc.returncode != 0:
                raise GitError(proc.stderr.strip() or "git clone failed")

        # Resolve exact SHA
        proc = _run_git(["rev-parse", "HEAD"], cwd=dest_path, timeout=timeout)
        if proc.returncode != 0:
            raise GitError(proc.stderr.strip() or "git rev-parse failed")
        sha = proc.stdout.strip()
        return sha

    except GitError:
        # Try ZIP fallback if GitHub
        gh = _github_owner_repo(url)
        if gh is None:
            raise
        # Ensure dest is empty (git may have created it)
        for p in list(dest_path.iterdir()) if dest_path.exists() else []:
            if p.is_file():
                p.unlink()
            else:
                shutil.rmtree(p, ignore_errors=True)
        return _zip_fallback(url, dest_path, ref, timeout=timeout)
