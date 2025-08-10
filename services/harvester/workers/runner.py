from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from ..clients.hub_client import HubClient
from ..discovery.scoring import score_entry
from ..store.models import Artifact, Job, get_session
from ..store.repo import put_artifact

AUTO_REGISTER_THRESHOLD = 0.8
MATRIXHUB_URL = "http://127.0.0.1:7300"


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 900) -> tuple[int, str, str]:
    """Run a subprocess with a wall-clock timeout, capturing stdout/stderr."""
    p = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out or "", err or ""
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return -1, out or "", (err or "") + "\n[timeout]"


def _persist_file(job_id: str, kind: str, path: Path) -> str | None:
    if not path.exists():
        return None
    b = path.read_bytes()
    uri = put_artifact(job_id, kind, b)
    db = get_session()
    try:
        db.add(Artifact(job_id=job_id, kind=kind, uri=uri, digest=None, bytes=len(b)))
        db.commit()
    finally:
        db.close()
    return uri


def _safe_json_load(s: str) -> dict:
    try:
        return json.loads(s)
    except Exception:
        return {}


def _auto_register_if_high(score: float, manifest_path: Path | None) -> None:
    if score < AUTO_REGISTER_THRESHOLD or not manifest_path or not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entity_uid = f"{manifest.get('type', 'mcp_server')}:{manifest.get('id')}@{manifest.get('version', '0.1.0')}"
        client = HubClient(MATRIXHUB_URL)
        client.install_manifest(entity_uid=entity_uid, target="./", manifest=manifest)
    except Exception:
        # best-effort only
        pass


def execute_job(job_id: str, payload: dict[str, Any]) -> None:
    """
    Execute a harvesting or packing job.

    Modes:
      - mode=="harvest_repo": runs `mcp-ingest harvest-repo <source>` and persists
        the repo-level index + all discovered manifests.
      - default (or mode=="pack"): backwards-compatible single-target pack flow.
    """
    db = get_session()
    try:
        job = db.get(Job, job_id)
        if not job:
            return
        job.status = "running"
        job.started_at = job.started_at or datetime.utcnow()
        db.commit()

        source = job.source
        options = job.options or {}
        mode = (options.get("mode") or payload.get("mode") or "pack").lower()
        timeout = int(options.get("timeout", 900))

        outdir = Path(tempfile.mkdtemp(prefix="mcp_job_"))

        if mode == "harvest_repo":
            # Build CLI command for clear timeout semantics
            cmd = [
                "mcp-ingest",
                "harvest-repo",
                source,
                "--out",
                str(outdir),
            ]
            publish = options.get("publish")
            if isinstance(publish, str) and publish:
                cmd += ["--publish", publish]
            if options.get("register"):
                cmd += ["--register"]
            matrixhub = options.get("matrixhub") or MATRIXHUB_URL
            if matrixhub:
                cmd += ["--matrixhub", matrixhub]

            rc, out, err = _run(cmd, timeout=timeout)

            # Always persist combined logs
            log_uri = put_artifact(job.id, "log", (out + "\n---\n" + err).encode("utf-8"))
            db.add(Artifact(job_id=job.id, kind="log", uri=log_uri, digest=None, bytes=None))

            if rc != 0:
                job.status = "failed"
                job.error = f"harvest-repo failed: rc={rc}"
                job.finished_at = datetime.utcnow()
                db.commit()
                return

            # Parse CLI JSON output for manifest/index paths and summary
            result = _safe_json_load(out)
            repo_index = result.get("repo_index_path") or result.get("index_path")
            manifest_paths = result.get("manifests") or []
            summary = result.get("summary") or {}

            # Persist repo-level index
            if repo_index:
                ip = Path(str(repo_index)).expanduser().resolve()
                if ip.exists():
                    ibytes = ip.read_bytes()
                    i_uri = put_artifact(job.id, "index", ibytes)
                    db.add(
                        Artifact(
                            job_id=job.id, kind="index", uri=i_uri, digest=None, bytes=len(ibytes)
                        )
                    )

            # Persist all manifests
            stored = 0
            for mp in manifest_paths:
                p = Path(str(mp)).expanduser().resolve()
                if not p.exists():
                    continue
                mbytes = p.read_bytes()
                m_uri = put_artifact(job.id, "manifest", mbytes)
                db.add(
                    Artifact(
                        job_id=job.id, kind="manifest", uri=m_uri, digest=None, bytes=len(mbytes)
                    )
                )
                stored += 1

            # Score (lightweight): if manifests produced, assign a baseline; higher if summary says validated
            validated = bool(summary.get("validated") or summary.get("register_performed"))
            score = 0.6 if stored > 0 else 0.0
            if validated:
                score = max(score, 0.8)

            job.confidence = score
            frameworks = summary.get("frameworks")
            if isinstance(frameworks, list):
                job.frameworks = ",".join(frameworks)
            job.status = "succeeded"
            job.finished_at = datetime.utcnow()
            db.commit()

            # Auto-register top entries only if requested via options and high score
            if options.get("auto_register_top") and repo_index:
                try:
                    # pick first manifest path for auto-register attempt
                    first_path = next(
                        (
                            Path(str(mp)).expanduser().resolve()
                            for mp in manifest_paths
                            if Path(str(mp)).exists()
                        ),
                        None,
                    )
                    _auto_register_if_high(score, first_path)
                except Exception:
                    pass

            return

        # -------------------------
        # Legacy/default: pack flow
        # -------------------------
        cmd = ["mcp-ingest", "pack", source, "--out", str(outdir)]
        if options.get("build") == "docker":
            cmd += ["--build", "docker"]
        if options.get("validate") in {"light", "strict"}:
            cmd += ["--validate", "strict"]

        rc, out, err = _run(cmd, timeout=timeout)

        log_uri = put_artifact(job.id, "log", (out + "\n---\n" + err).encode("utf-8"))
        db.add(Artifact(job_id=job.id, kind="log", uri=log_uri, digest=None, bytes=None))

        if rc != 0:
            job.status = "failed"
            job.error = f"mcp-ingest pack failed: rc={rc}"
            job.finished_at = datetime.utcnow()
            db.commit()
            return

        result: dict[str, Any] = _safe_json_load(out)
        manifest_path: str | None = None
        manifest_path = result.get("describe", {}).get("manifest_path") or result.get(
            "manifest_path"
        )

        if manifest_path:
            mp = Path(manifest_path).expanduser().resolve()
            if mp.exists():
                mbytes = mp.read_bytes()
                m_uri = put_artifact(job.id, "manifest", mbytes)
                db.add(
                    Artifact(
                        job_id=job.id, kind="manifest", uri=m_uri, digest=None, bytes=len(mbytes)
                    )
                )

        # Optional index
        ip = Path(outdir / "index.json")
        if ip.exists():
            ibytes = ip.read_bytes()
            i_uri = put_artifact(job.id, "index", ibytes)
            db.add(Artifact(job_id=job.id, kind="index", uri=i_uri, digest=None, bytes=len(ibytes)))

        # Compute score (detect+validation best-effort)
        detect_report = (
            result.get("detected", {}).get("report")
            if "detected" in result
            else result.get("report")
        )
        validation = result.get("register", {}) if "register" in result else {}
        score = score_entry(
            repo_metrics=None, detect_report=detect_report or {}, validation=validation or {}
        )

        job.confidence = score
        job.frameworks = (
            ",".join(detect_report.get("frameworks", [])) if isinstance(detect_report, dict) else ""
        )
        job.status = "succeeded"
        job.finished_at = datetime.utcnow()
        db.commit()

        # Optional auto-register if score high and manifest exists
        if manifest_path and score >= AUTO_REGISTER_THRESHOLD:
            _auto_register_if_high(score, Path(manifest_path))

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
