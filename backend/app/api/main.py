"""FastAPI application (Phase 2)."""

from __future__ import annotations

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import TimeoutError as PoolTimeout

from app.api.routes import router
from app.api.security import SecurityMiddleware

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

logger = logging.getLogger("tenderiq")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # A process kill mid-extraction leaves jobs stuck in RUNNING for ever, and
    # the UI polls them until the user gives up. Fail them at startup instead.
    from app.api.jobs import purge_old_jobs, recover_interrupted_jobs

    try:
        recovered, failed = recover_interrupted_jobs()
        if recovered:
            logger.warning("recovered %d interrupted job(s)", recovered)
        if failed:
            logger.warning("could not recover %d legacy job(s) without retained sources", failed)
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
    title="BidSense",
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
app.add_middleware(SecurityMiddleware)


@app.exception_handler(PoolTimeout)
async def database_overloaded(_: Request, exc: PoolTimeout) -> JSONResponse:
    """Shed excess load predictably instead of leaking an internal 500."""
    logger.warning("database pool saturated: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "The service is at capacity. Retry shortly."},
        headers={"Retry-After": "1"},
    )

app.include_router(router)


@app.get("/")
def root() -> dict:
    return {"name": "BidSense", "docs": "/docs", "health": "/api/health"}
