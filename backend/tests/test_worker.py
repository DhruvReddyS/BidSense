from __future__ import annotations

import threading
import uuid

from app.db.models import JobKind


def test_worker_claims_and_drains_one_job(tmp_path, monkeypatch):
    from app.api import jobs

    source = tmp_path / "queued.pdf"
    source.write_bytes(b"pdf")
    stop = threading.Event()
    claimed = [(uuid.uuid4(), JobKind.NOTIFICATION, source, {})]
    executed = []

    def next_job():
        if claimed:
            return claimed.pop()
        stop.set()
        return None

    monkeypatch.setattr(jobs, "claim_next_job", next_job)
    monkeypatch.setattr(jobs, "_run", lambda *args, **kwargs: executed.append((args, kwargs)))
    monkeypatch.setattr(jobs.settings, "ingest_workers", 2)
    monkeypatch.setattr(jobs.settings, "job_poll_seconds", 0.05)
    jobs.work_forever(stop)
    assert len(executed) == 1
    assert executed[0][0][1] is JobKind.NOTIFICATION
