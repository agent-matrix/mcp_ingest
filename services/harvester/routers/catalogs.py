from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc

from ..store.models import CatalogEntry, get_session

router = APIRouter(prefix="/catalogs", tags=["catalogs"])


@router.get("")
def list_catalogs(
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    framework: str | None = None,
    limit: int = Query(50, ge=1, le=500),
):
    db = get_session()
    try:
        q = (
            db.query(CatalogEntry)
            .filter(CatalogEntry.score >= min_score)
            .order_by(desc(CatalogEntry.last_seen))
        )
        if framework:
            q = q.filter(CatalogEntry.frameworks.contains(framework))
        rows = q.limit(limit).all()
        return [
            {
                "id": r.id,
                "key": r.key,
                "manifest_url": r.manifest_url,
                "score": r.score,
                "validated": r.validated,
                "frameworks": r.frameworks,
                "last_seen": r.last_seen,
            }
            for r in rows
        ]
    finally:
        db.close()


@router.get("/{entry_id}")
def get_catalog_entry(entry_id: int):
    db = get_session()
    try:
        r = db.get(CatalogEntry, entry_id)
        if not r:
            raise HTTPException(status_code=404, detail="not found")
        return {
            "id": r.id,
            "key": r.key,
            "manifest_url": r.manifest_url,
            "score": r.score,
            "validated": r.validated,
            "frameworks": r.frameworks,
            "last_seen": r.last_seen,
            "notes": r.notes,
        }
    finally:
        db.close()
