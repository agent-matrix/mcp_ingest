from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------
DB_URL = os.getenv("HARVESTER_DB_URL", "sqlite:///harvester.db")

engine = create_engine(DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


# ---------------------------------------------------------------------------
# SQLAlchemy models
# ---------------------------------------------------------------------------
class Job(Base):
    """Harvest/pack job lifecycle.

    Added fields for repo harvesting at scale:
      • mode: "pack" (default) or "harvest_repo".
      • sha / repo_name: metadata for sources resolved from git/zip.
      • manifests_count: how many manifests were produced for the repo.
      • transports_summary: JSON summary per transport (e.g., {"SSE": 10, "STDIO": 2}).
      • exec_present_count: how many manifests had an exec block present.
    """

    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    mode = Column(String, nullable=False, default="pack", index=True)  # pack|harvest_repo

    source = Column(String, nullable=False)  # git/url/zip/folder
    status = Column(String, nullable=False, default="queued")  # queued|running|succeeded|failed
    options = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    confidence = Column(Float, nullable=True)  # detector/validate composite
    frameworks = Column(String, nullable=True)  # comma-separated tags

    # New: repo metadata & harvest summaries
    sha = Column(String, nullable=True, index=True)
    repo_name = Column(String, nullable=True, index=True)
    manifests_count = Column(Integer, nullable=True, default=0)
    transports_summary = Column(JSON, nullable=True)  # {"SSE": int, "STDIO": int, "WS": int}
    exec_present_count = Column(Integer, nullable=True, default=0)

    artifacts = relationship("Artifact", back_populates="job", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_jobs_status_created", "status", "created_at"),)


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.id"), index=True, nullable=False)
    kind = Column(String, nullable=False)  # manifest|index|sbom|log|other
    uri = Column(String, nullable=False)  # file:// or s3:// or ghpages path
    digest = Column(String, nullable=True)
    bytes = Column(Integer, nullable=True)

    job = relationship("Job", back_populates="artifacts")


class CatalogEntry(Base):
    """Indexable catalog row for a single manifest.

    Added fields so we can filter quickly in UIs:
      • transport: SSE|STDIO|WS
      • exec_present: True if the manifest/server block has an exec command.
    """

    __tablename__ = "catalog_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, unique=True, nullable=False)  # normalized repo@sha:path
    manifest_url = Column(String, nullable=False)
    score = Column(Float, nullable=False, default=0.0)
    validated = Column(Boolean, default=False)
    last_seen = Column(DateTime, default=datetime.utcnow, nullable=False)

    # tags/filters
    frameworks = Column(String, nullable=True)  # comma-separated
    transport = Column(String, nullable=True, index=True)  # SSE|STDIO|WS
    exec_present = Column(Boolean, default=False)

    notes = Column(Text, nullable=True)

    __table_args__ = (Index("ix_catalog_transport_validated", "transport", "validated"),)


# ---------------------------------------------------------------------------
# Pydantic API models
# ---------------------------------------------------------------------------
class JobCreate(BaseModel):
    source: str
    mode: Literal["pack", "harvest_repo"] = "pack"
    options: dict[str, Any] = Field(default_factory=dict)


class JobView(BaseModel):
    id: str
    status: str
    source: str
    mode: str
    summary: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    errors: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return SessionLocal()


def job_to_view(db: Session, job: Job) -> JobView:
    arts = db.query(Artifact).filter(Artifact.job_id == job.id).all()
    transports_summary = job.transports_summary or {}

    summary: dict[str, Any] = {
        "confidence": job.confidence,
        "frameworks": (job.frameworks or ""),
        "sha": job.sha,
        "repo_name": job.repo_name,
        "manifests_count": job.manifests_count or 0,
        "transports": transports_summary,
        "exec_present_count": job.exec_present_count or 0,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }

    return JobView(
        id=job.id,
        status=job.status,
        source=job.source,
        mode=job.mode,
        summary=summary,
        artifacts=[
            {"kind": a.kind, "uri": a.uri, "digest": a.digest, "bytes": a.bytes} for a in arts
        ],
        errors=job.error,
    )
