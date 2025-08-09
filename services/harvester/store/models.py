from __future__ import annotations
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, List

from sqlalchemy import (
    create_engine, Column, String, Text, Integer, DateTime, Float, JSON, ForeignKey, Boolean
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from pydantic import BaseModel, Field

DB_URL = os.getenv("HARVESTER_DB_URL", "sqlite:///harvester.db")

engine = create_engine(DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

# --- SQLAlchemy models --------------------------------------------------------

class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source = Column(String, nullable=False)  # git/url/zip/folder
    status = Column(String, nullable=False, default="queued")  # queued|running|succeeded|failed
    options = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    confidence = Column(Float, nullable=True)        # detector/validate composite
    frameworks = Column(String, nullable=True)       # comma-separated tags

    artifacts = relationship("Artifact", back_populates="job", cascade="all, delete-orphan")

class Artifact(Base):
    __tablename__ = "artifacts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.id"), index=True, nullable=False)
    kind = Column(String, nullable=False)      # manifest|index|sbom|log|other
    uri = Column(String, nullable=False)       # file:// or s3://
    digest = Column(String, nullable=True)
    bytes = Column(Integer, nullable=True)

    job = relationship("Job", back_populates="artifacts")

class CatalogEntry(Base):
    __tablename__ = "catalog_entries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, unique=True, nullable=False)  # normalized repo@sha:path
    manifest_url = Column(String, nullable=False)
    score = Column(Float, nullable=False, default=0.0)
    validated = Column(Boolean, default=False)
    last_seen = Column(DateTime, default=datetime.utcnow, nullable=False)
    frameworks = Column(String, nullable=True)  # comma-separated
    notes = Column(Text, nullable=True)

# --- Pydantic API models ------------------------------------------------------

class JobCreate(BaseModel):
    source: str
    options: Dict[str, Any] = Field(default_factory=dict)

class JobView(BaseModel):
    id: str
    status: str
    source: str
    summary: Dict[str, Any] = Field(default_factory=dict)
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    errors: Optional[str] = None

# --- Helpers ------------------------------------------------------------------

def init_db() -> None:
    Base.metadata.create_all(engine)

def get_session() -> Session:
    return SessionLocal()

def job_to_view(db: Session, job: Job) -> JobView:
    arts = db.query(Artifact).filter(Artifact.job_id == job.id).all()
    return JobView(
        id=job.id,
        status=job.status,
        source=job.source,
        summary={
            "confidence": job.confidence,
            "frameworks": (job.frameworks or ""),
        },
        artifacts=[
            {"kind": a.kind, "uri": a.uri, "digest": a.digest, "bytes": a.bytes} for a in arts
        ],
        errors=job.error,
    )
