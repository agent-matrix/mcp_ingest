from __future__ import annotations
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ..store.models import get_session, init_db, Job, job_to_view, JobCreate
from ..workers.queue import InMemoryQueue

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Queue is injected by app.py via dependency override in prod; in dev we keep a module-level.
_queue = InMemoryQueue()

class JobId(BaseModel):
    id: str

@router.post("", response_model=JobId)
def submit_job(payload: JobCreate):
    db = get_session()
    try:
        job = Job(source=payload.source, status="queued", options=payload.options or {})
        db.add(job); db.commit(); db.refresh(job)
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
    """Lightweight discover: enqueue sources from GitHub search for a query (server-side default queries exist)."""
    from ..discovery.github_search import search_sources
    sources = search_sources(limit=25)
    db = get_session()
    try:
        enqueued = []
        for src in sources:
            job = Job(source=src, status="queued", options={"build":"docker","validate":"light"})
            db.add(job); db.commit(); db.refresh(job)
            _queue.enqueue({"id": job.id, "source": job.source, "options": job.options})
            enqueued.append(job.id)
        return {"count": len(enqueued), "job_ids": enqueued}
    finally:
        db.close()

# Helper for app.py
def get_queue():
    return _queue
