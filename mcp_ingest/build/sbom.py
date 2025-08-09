from __future__ import annotations
import json, os, shutil, subprocess, time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

__all__ = [
    "generate_sbom_for_source",
    "generate_sbom_for_image",
    "emit_provenance",
]


# --- common helpers --------------------------------------------------------

def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _run(cmd: list[str], cwd: Optional[Path] = None, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)


# --- SBOM for source (CycloneDX-like minimal JSON) ------------------------

def _pip_freeze(cwd: Path) -> List[Dict[str, str]]:
    try:
        p = _run(["python", "-m", "pip", "freeze"], cwd=cwd, timeout=120)
        if p.returncode == 0:
            out: List[Dict[str, str]] = []
            for line in (p.stdout or "").splitlines():
                if "==" in line:
                    name, ver = line.strip().split("==", 1)
                    out.append({"name": name, "version": ver})
            return out
    except Exception:
        pass
    return []


def generate_sbom_for_source(source: str, *, out_path: str | Path | None = None) -> Path:
    """Generate a minimal SBOM for a Python source tree.

    Strategy: if requirements.txt exists, read; else pip freeze (best-effort).
    Output is a CycloneDX-like JSON with components[] (name, version).
    """
    src = Path(source).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"source not found: {src}")

    components: List[Dict[str, str]] = []
    req = src / "requirements.txt"
    if req.exists():
        for line in req.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "==" in line:
                name, ver = line.split("==", 1)
                components.append({"name": name.strip(), "version": ver.strip()})
            else:
                components.append({"name": line, "version": "*"})
    else:
        components = _pip_freeze(src)

    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.4",
        "version": 1,
        "metadata": {
            "timestamp": _ts(),
            "component": {"type": "application", "name": src.name},
        },
        "components": components,
    }

    out = Path(out_path or (src / "sbom.source.json"))
    out.write_text(json.dumps(sbom, indent=2, sort_keys=True), encoding="utf-8")
    return out


# --- SBOM for image (syft if available; minimal fallback) -----------------

def _which(prog: str) -> Optional[str]:
    return shutil.which(prog)


def generate_sbom_for_image(image_ref: str, *, out_path: str | Path | None = None) -> Path:
    """Generate an SBOM for an OCI image.

    Uses `syft` if available; otherwise emits a minimal JSON stub with the image ref.
    """
    out = Path(out_path or Path.cwd() / "sbom.image.json")
    try:
        if _which("syft"):
            p = _run(["syft", "-o", "json", image_ref], timeout=300)
            if p.returncode == 0 and p.stdout:
                out.write_text(p.stdout, encoding="utf-8")
                return out
    except Exception:
        pass

    stub = {
        "schema": "stub.syft",
        "generated": _ts(),
        "image": image_ref,
        "note": "syft not found; minimal metadata only",
    }
    out.write_text(json.dumps(stub, indent=2, sort_keys=True), encoding="utf-8")
    return out


# --- Provenance (SLSA-like minimal doc) -----------------------------------

def emit_provenance(meta: Dict[str, object], *, out_path: str | Path | None = None) -> Path:
    """Emit a minimal provenance/attestation JSON file.

    Includes generator, build digest, commit sha, timestamps, and arbitrary metadata.
    """
    payload = {
        "type": "mcp-ingest.provenance",
        "generated": _ts(),
        **(meta or {}),
    }
    out = Path(out_path or Path.cwd() / "provenance.json")
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out
