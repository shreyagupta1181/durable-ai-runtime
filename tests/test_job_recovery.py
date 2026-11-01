
from datetime import datetime, timedelta, timezone

from app.models.job import Job
from app.models.event import RunEvent
from app.services.job_service import recover_expired_jobs


def test_expired_job_is_requeued(db, run):
    job = db.query(Job).filter(Job.run_id == run.id).one()

    now = datetime.now(timezone.utc)

    # Simulate a worker crashing while processing this run.
    run.status = "running"

    job.status = "running"
    job.attempts = 1
    job.max_attempts = 3
    job.locked_by = "worker-crashed"
    job.locked_at = now - timedelta(seconds=60)
    job.heartbeat_at = now - timedelta(seconds=60)
    job.lease_expires_at = now - timedelta(seconds=30)

    db.commit()

    result = recover_expired_jobs(db)

    db.refresh(job)
    db.refresh(run)

    assert result == {"requeued": 1, "failed": 0}

    # Job recovery
    assert job.status == "queued"
    assert job.locked_by is None
    assert job.locked_at is None
    assert job.lease_expires_at is None
    assert job.heartbeat_at is None
    assert job.available_at > now

    # Run recovery
    assert run.status == "retrying"

    # Event persistence
    events = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run.id)
        .order_by(RunEvent.seq)
        .all()
    )

    event_types = [event.type for event in events]

    assert "job_requeued" in event_types
    assert "run_status_changed" in event_types

    requeue_event = next(
        event for event in events
        if event.type == "job_requeued"
    )

    assert requeue_event.payload["reason"] == "lease_expired"


def test_expired_job_fails_after_max_attempts(db, run):
    job = db.query(Job).filter(Job.run_id == run.id).one()

    now = datetime.now(timezone.utc)

    # Simulate a worker crashing on its final allowed attempt.
    run.status = "running"

    job.status = "running"
    job.attempts = 3
    job.max_attempts = 3
    job.locked_by = "worker-crashed"
    job.locked_at = now - timedelta(seconds=60)
    job.heartbeat_at = now - timedelta(seconds=60)
    job.lease_expires_at = now - timedelta(seconds=30)

    db.commit()

    result = recover_expired_jobs(db)

    db.refresh(job)
    db.refresh(run)

    assert result == {"requeued": 0, "failed": 1}

    # Job failure
    assert job.status == "failed"
    assert job.locked_by is None
    assert job.locked_at is None
    assert job.lease_expires_at is None
    assert job.heartbeat_at is None

    # Run failure
    assert run.status == "failed"

    # Event persistence
    events = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run.id)
        .order_by(RunEvent.seq)
        .all()
    )

    event_types = [event.type for event in events]

    assert "job_failed" in event_types
    assert "run_status_changed" in event_types

    failure_event = next(
        event for event in events
        if event.type == "job_failed"
    )

    assert failure_event.payload["reason"] == (
        "lease_expired_attempts_exhausted"
    )
