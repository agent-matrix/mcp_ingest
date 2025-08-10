from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator

from ..store.models import Job, get_session, job_to_view
from ..workers.queue import InMemoryQueue

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Queue is injected by app.py via dependency override in prod; in dev we keep a module-level.
_queue = InMemoryQueue()


# ----------------------------
# Request/Response models
# ----------------------------
class JobId(BaseModel):
    id: str


class JobSubmit(BaseModel):
    """Submit a job to the harvester.

    Examples:
      {"mode": "harvest_repo", "source": "https://github.com/modelcontextprotocol/servers/archive/refs/heads/main.zip", "options": {}}
      {"source": "https://github.com/org/repo.git", "options": {"mode":"pack","build":"docker"}}
    """

    source: str = Field(..., description="git URL, zip URL, or local path")
    mode: str | None = Field(
        default=None,
        description=(
            "Job mode. If 'harvest_repo', the worker will run the repo-wide harvester; "
            "otherwise it defaults to single-target 'pack'."
        ),
    )
    options: dict[str, Any] | None = Field(
        default=None,
        description="Additional execution options (build/validate/publish/register/etc.)",
    )

    @validator("source")
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("source must be a non-empty string")
        return v.strip()


# ----------------------------
# Endpoints
# ----------------------------
@router.post("", response_model=JobId)
def submit_job(payload: JobSubmit) -> JobId:
    """Enqueue a job.

    Accepts both legacy and new payloads. If a top-level `mode` is provided, it is copied
    into the `options["mode"]` field, so workers can switch between `pack` and `harvest_repo`.
    """
    db = get_session()
    try:
        # Normalize options
        options: dict[str, Any] = dict(payload.options or {})
        if payload.mode:
            options.setdefault("mode", payload.mode)

        job = Job(source=payload.source, status="queued", options=options)
        db.add(job)
        db.commit()
        db.refresh(job)

        jid = job.id
        _queue.enqueue({"id": jid, "source": job.source, "options": job.options})
        return JobId(id=jid)
    finally:
        db.close()


@router.get("/{job_id}")
def get_job(job_id: str):
    db = get_session()
    try:
        job = db.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job_to_view(db, job).dict()
    finally:
        db.close()


@router.post("/discover")
def discover_jobs(query: str = ""):
    """Lightweight discover: enqueue sources from GitHub search for a query.

    Server-side defaults are used when `query` is empty.
    """
    from ..discovery.github_search import search_sources

    sources = search_sources(limit=25)
    db = get_session()
    try:
        enqueued = []
        for src in sources:
            job = Job(source=src, status="queued", options={"build": "docker", "validate": "light"})
            db.add(job)
            db.commit()
            db.refresh(job)
            _queue.enqueue({"id": job.id, "source": job.source, "options": job.options})
            enqueued.append(job.id)
        return {"count": len(enqueued), "job_ids": enqueued}
    finally:
        db.close()


# Helper for app.py


def get_queue():
    return _queue
