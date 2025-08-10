from __future__ import annotations

"""
Harvest router
--------------
A tiny sugar endpoint to enqueue repo-wide harvest jobs.

POST /harvest/repo  {"source": "<git|zip|dir>", "options": {...}}
→ enqueues a Job with mode="harvest_repo" and returns {id}.

Works alongside the existing jobs & worker pipeline. The worker
(services.harvester.workers.runner.execute_job) must support
mode=="harvest_repo" (it does in our Stage-2 edits).
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..store.models import Job, get_session
from .jobs import get_queue  # reuse the same in-memory queue helper

router = APIRouter(prefix="/harvest", tags=["harvest"])


class JobId(BaseModel):
    id: str


class HarvestRepoRequest(BaseModel):
    source: str = Field(..., description="git URL, zip URL, or local path")
    options: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional job options, e.g. {build: 'docker', validate: 'light', "
            "publish: 's3://bucket/prefix/', register: false, timeout: 900}"
        ),
    )


@router.post("/repo", response_model=JobId)
def harvest_repo(req: HarvestRepoRequest) -> JobId:
    """Enqueue a repo-wide harvest job.

    The worker will clone/download/extract the repo, detect multiple MCP servers,
    emit per-server manifests, write a repo-level index.json, and (optionally)
    publish or register into MatrixHub depending on options.
    """
    source = (req.source or "").strip()
    if not source:
        raise HTTPException(status_code=400, detail="source is required")

    db = get_session()
    try:
        job = Job(
            mode="harvest_repo",
            source=source,
            status="queued",
            options=req.options or {},
            created_at=datetime.utcnow(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        # Enqueue for the background worker
        queue = get_queue()
        queue.enqueue(
            {
                "id": job.id,
                "mode": job.mode,
                "source": job.source,
                "options": job.options or {},
            }
        )

        return JobId(id=job.id)
    finally:
        db.close()
