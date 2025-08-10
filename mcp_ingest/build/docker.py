from __future__ import annotations

import hashlib
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = ["BuildResult", "build_image", "tag_image"]


def _hash_path(path: Path) -> str:
    # quick-and-dirty content hash (filenames + mtimes) to cache builds
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(path)).encode())
            h.update(str(int(p.stat().st_mtime)).encode())
    return h.hexdigest()


@dataclass
class BuildResult:
    success: bool
    image_ref: str | None
    digest: str | None
    logs: str
    labels: dict[str, str]

    def to_dict(self):
        d = asdict(self)
        d["labels"] = dict(self.labels or {})
        return d


def _run(cmd, *, cwd: Path | None = None, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


def build_image(
    source: str,
    *,
    runtime: str = "python:3.11-slim",
    lockfile: str | None = None,
    strategy: str = "dockerfile",
    image_name: str | None = None,
    labels: dict[str, str] | None = None,
) -> BuildResult:
    """Build an OCI image for the given source directory.

    Strategy: generate a minimal Dockerfile if none present.
    Installs deps via pip (prefers requirements.txt; else pyproject).
    """
    src = Path(source).expanduser().resolve()
    if not src.exists():
        return BuildResult(False, None, None, logs=f"source not found: {src}", labels={})

    lbls = {
        **(labels or {}),
        "org.opencontainers.image.created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "org.opencontainers.image.source": str(src),
    }

    # Guess a name from folder if not provided
    name = image_name or f"mcp-{src.name.lower().replace('_', '-')}"

    # Create a temporary Dockerfile
    df = f"""
FROM {runtime}
ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1
RUN apt-get update -y && apt-get install -y --no-install-recommends \\
    curl ca-certificates build-essential git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
# Pinned deps if requirements.txt present; else best-effort install project
RUN python -m pip install --upgrade pip \\
    && if [ -f requirements.txt ]; then pip install -r requirements.txt; \\
    elif [ -f pyproject.toml ]; then pip install .; \\
    else echo "No requirements found; skipping"; fi
EXPOSE 6288
# Default command is a no-op; caller provides CMD at runtime for validation
CMD ["python", "-c", "print('image built; provide CMD at run time')"]
"""

    # Build context = src; use stdin Dockerfile
    lbl_flags = []
    for k, v in lbls.items():
        lbl_flags += ["--label", f"{k}={v}"]

    try:
        # We need to pipe the Dockerfile content to the docker build command
        proc = subprocess.run(
            ["docker", "build", "-f", "-", "-t", name, *lbl_flags, str(src)],
            input=df,
            text=True,
            capture_output=True,
            check=True,
        )
        logs = proc.stdout + "\n" + proc.stderr

        # Inspect image ID / digest
        inspect = _run(
            ["docker", "images", "--no-trunc", "--format", "{{.Repository}}:{{.Tag}} {{.ID}}", name]
        )
        img_line = inspect.stdout.strip().splitlines()[:1]
        digest = None
        if img_line:
            # .ID is content-addressable id (sha256:...)
            parts = img_line[0].split()
            digest = parts[1] if len(parts) > 1 else None

        # Create a stable tag by digest short
        if digest and digest.startswith("sha256:"):
            short = digest.split(":", 1)[1][:12]
        else:
            short = _hash_path(src)[:12]
        stable_tag = f"{name}:{short}"
        _run(["docker", "tag", name, stable_tag])

        return BuildResult(True, stable_tag, digest, logs=logs, labels=lbls)
    except subprocess.CalledProcessError as e:
        logs = e.stdout + "\n" + e.stderr
        return BuildResult(False, None, None, logs=logs, labels=lbls)
    except Exception as e:
        return BuildResult(False, None, None, logs=str(e), labels=lbls)


def tag_image(digest: str, tag: str) -> str:
    """Tag an existing local image (by name or digest) with a new tag, returns tag."""
    try:
        _run(["docker", "tag", digest, tag])
        return tag
    except Exception as e:  # pragma: no cover
        # FIX: Chain the exception to preserve the original traceback.
        raise RuntimeError(str(e)) from e
