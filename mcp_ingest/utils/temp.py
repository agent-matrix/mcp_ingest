from __future__ import annotations

"""
Safe temporary workspace helpers for mcp_ingest.

Usage
-----
from mcp_ingest.utils.temp import mktempdir

with mktempdir(prefix="mcp-") as work:
    # `work` is a pathlib.Path pointing to a unique, empty temp directory
    ...
# directory is removed automatically, even on exceptions

Design goals
------------
• No temp leaks in normal or exceptional flows
• Robust cleanup on Windows & POSIX (chmod-on-error retry)
• Option to keep directory on error for debugging via flag or env var
"""

import atexit
import os
import shutil
import tempfile
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

__all__ = ["SafeTemporaryDirectory", "mktempdir"]


def _chmod_and_retry(func, path, exc_info):  # pragma: no cover - platform dependent edge cases
    """shutil.rmtree onerror handler: make path writable and retry.

    This helps on Windows where read-only files can block deletion.
    """
    try:
        os.chmod(path, 0o700)
        func(path)
    except Exception:
        # Give up; the atexit fallback (same handler) will try once more
        pass


@dataclass
class SafeTemporaryDirectory(AbstractContextManager[Path]):
    """Context manager for a temporary directory with robust cleanup.

    Parameters
    ----------
    prefix : str
        Directory name prefix (default: "mcp-").
    base_dir : Optional[str | os.PathLike]
        Parent directory to create temps under. Defaults to system temp dir.
    delete : bool
        If False, do not delete on exit. Useful for debugging.
    keep_on_error : bool
        If True and an exception escapes the context, keep the directory for forensics.
    env_keep_flag : str
        If this environment variable is set to a truthy value ("1", "true", "yes"),
        the directory will be kept regardless of `delete` on normal exit.
    """

    prefix: str = "mcp-"
    base_dir: Path | None = None
    delete: bool = True
    keep_on_error: bool = False
    env_keep_flag: str = "MCP_INGEST_KEEP_TEMPS"

    # Internal
    _path: Path | None = None
    _cleaned: bool = False

    def __post_init__(self) -> None:
        base = Path(self.base_dir) if self.base_dir is not None else None
        self._path = Path(tempfile.mkdtemp(prefix=self.prefix, dir=str(base) if base else None))
        # Best-effort: ensure dir is private to this user by default
        try:
            os.chmod(self._path, 0o700)
        except Exception:
            pass
        atexit.register(self._atexit_cleanup)

    # --- Context manager protocol -------------------------------------------------
    def __enter__(self) -> Path:  # returns the path directly for ergonomic usage
        assert self._path is not None
        return self._path

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> bool | None:
        # Keep if requested by flag/env and an exception occurred
        keep_env = os.getenv(self.env_keep_flag, "").strip().lower() in {"1", "true", "yes"}
        if self.keep_on_error and exc_type is not None:
            return None  # do not delete; propagate exception
        if keep_env and exc_type is not None:
            return None  # do not delete; propagate exception
        # Normal path
        if self.delete:
            self.cleanup()
        return None  # do not suppress exceptions

    # --- Public API ---------------------------------------------------------------
    @property
    def path(self) -> Path:
        assert self._path is not None, "Temporary directory not initialized"
        return self._path

    def cleanup(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        try:
            if self._path and self._path.exists():
                shutil.rmtree(self._path, onerror=_chmod_and_retry)
        finally:
            # Best-effort: remove atexit hook reference so it won’t run twice
            try:
                atexit.unregister(self._atexit_cleanup)
            except Exception:
                pass

    # --- Private -----------------------------------------------------------------
    def _atexit_cleanup(self) -> None:  # pragma: no cover - atexit hard to unit test
        try:
            if self.delete and not self._cleaned and self._path and self._path.exists():
                shutil.rmtree(self._path, onerror=_chmod_and_retry)
        except Exception:
            # Last-resort cleanup; ignore errors on interpreter shutdown
            pass


def mktempdir(
    prefix: str = "mcp-",
    *,
    base_dir: str | Path | None = None,
    delete: bool = True,
    keep_on_error: bool = False,
    env_keep_flag: str = "MCP_INGEST_KEEP_TEMPS",
) -> SafeTemporaryDirectory:
    """Create a safe temporary directory context manager.

    Returns a `SafeTemporaryDirectory` which yields a `pathlib.Path` when used
    as a context manager.

    Examples
    --------
    >>> from mcp_ingest.utils.temp import mktempdir
    >>> with mktempdir() as d:
    ...     (d / "hello.txt").write_text("hi")
    ...
    >>> # directory removed automatically
    """
    base = Path(base_dir).expanduser().resolve() if base_dir is not None else None
    return SafeTemporaryDirectory(
        prefix=prefix,
        base_dir=base,
        delete=delete,
        keep_on_error=keep_on_error,
        env_keep_flag=env_keep_flag,
    )
