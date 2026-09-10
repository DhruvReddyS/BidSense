"""Durable ingestion worker for horizontally scaled deployments.

Run one or more copies with ``python -m scripts.worker``. Each process claims
jobs through PostgreSQL ``FOR UPDATE SKIP LOCKED``; no two workers can execute
the same row, and API replicas never hold extraction work in memory.
"""

from __future__ import annotations

import logging
import signal
import threading

from app.api.jobs import recover_interrupted_jobs, work_forever
from app.config import settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if settings.job_execution_mode != "database":
        raise SystemExit(
            "Set JOB_EXECUTION_MODE=database before starting a dedicated worker."
        )

    stop = threading.Event()

    def request_stop(signum, _frame) -> None:
        logging.getLogger(__name__).info("signal %s received; draining active jobs", signum)
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    recovered, failed = recover_interrupted_jobs()
    if recovered or failed:
        logging.getLogger(__name__).info(
            "startup recovery: %d requeued, %d failed", recovered, failed
        )
    work_forever(stop)


if __name__ == "__main__":
    main()
