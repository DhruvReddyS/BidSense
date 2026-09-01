"""FastAPI application (Phase 2)."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="TenderIQ",
    description="Tender intelligence platform — Part 1 (vendor compliance) API.",
    version="0.2.0",
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
