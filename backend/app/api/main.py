"""FastAPI application (Phase 2)."""

from __future__ import annotations

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

logger = logging.getLogger("tenderiq")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # A process kill mid-extraction leaves jobs stuck in RUNNING for ever, and
    # the UI polls them until the user gives up. Fail them at startup instead.
    from app.api.jobs import purge_old_jobs, reap_stale_jobs

    try:
        reaped = reap_stale_jobs()
        if reaped:
            logger.warning("marked %d interrupted job(s) as failed", reaped)
    except Exception:
        logger.exception("could not reap stale jobs at startup")

    try:
        purged = purge_old_jobs()
        if purged:
            logger.info("purged %d job record(s) past the retention window", purged)
    except Exception:
        logger.exception("could not purge old jobs at startup")
    yield


app = FastAPI(
    title="TenderIQ",
    description="Tender intelligence platform — Part 1 (vendor compliance) API.",
    version="0.3.0",
    lifespan=lifespan,
)

# The Next.js dev server runs on 3000. Tightened before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root() -> dict:
    return {"name": "TenderIQ", "docs": "/docs", "health": "/api/health"}
