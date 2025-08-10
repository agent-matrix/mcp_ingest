from __future__ import annotations

import threading
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import catalogs as catalogs_router
from .routers import jobs as jobs_router
from .store.models import init_db
from .workers.runner import worker_loop


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="MCP Harvester", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(jobs_router.router)
    app.include_router(catalogs_router.router)

    # Background worker (dev in-memory queue)
    q = jobs_router.get_queue()
    stop = threading.Event()
    t = threading.Thread(target=worker_loop, args=(q, stop), daemon=True)
    t.start()

    @app.on_event("shutdown")
    def _shutdown():
        stop.set()
        time.sleep(0.2)

    @app.get("/healthz")
    def health():
        return {"ok": True}

    return app


app = create_app()
