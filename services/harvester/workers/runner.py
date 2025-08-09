from __future__ import annotations
import json
import shlex
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..store.models import get_session, Job, Artifact, CatalogEntry
from ..store.repo import put_artifact
from ..discovery.scoring import score_entry
from ..clients.hub_client import HubClient

AUTO_REGISTER_THRESHOLD = 0.8
MATRIXHUB_URL = "http://127.0.0.1:7300"

def _run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 900) -> Tuple[int, str, str]:
    p = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out or "", err or ""
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return -1, out or "", (err or "") + "\n[timeout]"

def execute_job(job_id: str, payload: Dict[str, Any]) -> None:
    """Execute: mcp-ingest pack <source> --out <tmp> [flags] and persist artifacts/results."""
    db = get_session()
    try:
        job = db.get(Job, job_id)
        if not job: return
        job.status = "running"
        job.started_at = job.started_at or datetime.utcnow()
        db.commit()

        source = job.source
        options = job.options or {}
        outdir = Path(tempfile.mkdtemp(prefix="mcp_pack_"))

        cmd = ["mcp-ingest", "pack", source, "--out", str(outdir)]
        if options.get("build") == "docker":
            cmd += ["--build", "docker"]
        if options.get("validate") in {"light", "strict"}:
            cmd += ["--validate", "strict"]
        # Publishing & register flags are deferred by default in harvester
        rc, out, err = _run(cmd, timeout=options.get("timeout", 900))

        log_uri = put_artifact(job.id, "log", (out + "\n---\n" + err).encode("utf-8"))
        db.add(Artifact(job_id=job.id, kind="log", uri=log_uri, digest=None, bytes=None))

        if rc != 0:
            job.status = "failed"
            job.error = f"mcp-ingest failed: rc={rc}"
            db.commit()
            return

        result: Dict[str, Any] = {}
        manifest_path: Optional[str] = None
        try:
            result = json.loads(out)
            manifest_path = result.get("describe", {}).get("manifest_path") or result.get("manifest_path")
        except Exception:
            # best effort: locate manifest.json under outdir
            if (outdir / "manifest.json").exists():
                manifest_path = str(outdir / "manifest.json")

        if manifest_path:
            mp = Path(manifest_path).expanduser().resolve()
            if mp.exists():
                mbytes = mp.read_bytes()
                m_uri = put_artifact(job.id, "manifest", mbytes)
                db.add(Artifact(job_id=job.id, kind="manifest", uri=m_uri, digest=None, bytes=len(mbytes)))
        # Optional index
        ip = Path(outdir / "index.json")
        if ip.exists():
            ibytes = ip.read_bytes()
            i_uri = put_artifact(job.id, "index", ibytes)
            db.add(Artifact(job_id=job.id, kind="index", uri=i_uri, digest=None, bytes=len(ibytes)))

        # Compute score (detect+validation best-effort)
        detect_report = result.get("detected", {}).get("report") if "detected" in result else result.get("report")
        validation = result.get("register", {}) if "register" in result else {}
        score = score_entry(repo_metrics=None, detect_report=detect_report or {}, validation=validation or {})

        job.confidence = score
        job.frameworks = ",".join(detect_report.get("frameworks", [])) if isinstance(detect_report, dict) else ""
        job.status = "succeeded"
        job.finished_at = datetime.utcnow()
        db.commit()

        # Optional auto-register if score high and manifest exists
        if score >= AUTO_REGISTER_THRESHOLD and manifest_path:
            try:
                manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                entity_uid = f"{manifest.get('type','mcp_server')}:{manifest.get('id')}@{manifest.get('version','0.1.0')}"
                client = HubClient(MATRIXHUB_URL)
                client.install_manifest(entity_uid=entity_uid, target="./", manifest=manifest)
            except Exception:
                pass

    finally:
        db.close()

def worker_loop(queue, stop_event) -> None:
    while not stop_event.is_set():
        try:
            jid, payload = queue.dequeue(timeout=1.0)
            try:
                execute_job(jid, payload)
                queue.ack(jid)
            except Exception:
                queue.nack(jid)
        except Exception:
            continue
