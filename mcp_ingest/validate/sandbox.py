from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

__all__ = ["SandboxResult", "run_process"]


@dataclass
class SandboxResult:
    ok: bool
    returncode: int | None
    elapsed_secs: float
    stdout: str
    stderr: str
    timed_out: bool


_def_env = os.environ.copy()


def _set_limits(mem_limit_mb: int | None) -> None:  # pragma: no cover - platform specific
    """best-effort memory limiter for POSIX via resource.setrlimit."""
    if mem_limit_mb is None:
        return
    try:
        import resource  # type: ignore

        soft = mem_limit_mb * 1024 * 1024
        hard = soft
        # address space
        resource.setrlimit(resource.RLIMIT_AS, (soft, hard))
        # data segment
        resource.setrlimit(resource.RLIMIT_DATA, (soft, hard))
    except Exception:
        # not supported on this platform; proceed without limits
        pass


def run_process(
    cmd: list[str],
    *,
    timeout: int = 30,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    mem_limit_mb: int | None = None,
) -> SandboxResult:
    """Run a local process with optional time/memory limits and capture logs.

    Notes:
      • On POSIX, memory limits are best-effort via resource.setrlimit.
      • On Windows, memory limits are ignored (process is still time-limited).
    """
    start = time.perf_counter()
    try:
        preexec = None
        if os.name == "posix":  # only POSIX supports preexec_fn
            preexec = lambda: _set_limits(mem_limit_mb)
        p = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            env={**_def_env, **(env or {})},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            preexec_fn=preexec,
        )
        try:
            out, err = p.communicate(timeout=timeout)
            rc = p.returncode
            ok = rc == 0
            return SandboxResult(
                ok=ok,
                returncode=rc,
                elapsed_secs=time.perf_counter() - start,
                stdout=out or "",
                stderr=err or "",
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
            return SandboxResult(
                ok=False,
                returncode=None,
                elapsed_secs=time.perf_counter() - start,
                stdout=out or "",
                stderr=(err or "") + "\n[timeout]",
                timed_out=True,
            )
    except Exception as e:  # unexpected launcher errors
        return SandboxResult(
            ok=False,
            returncode=None,
            elapsed_secs=time.perf_counter() - start,
            stdout="",
            stderr=str(e),
            timed_out=False,
        )
