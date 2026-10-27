from datetime import datetime, timedelta, timezone

from app.models.job import Job
from app.services.job_service import recover_expired_jobs


def test_expired_job_is_requeued(db, run):
    job = db.query(Job).filter(Job.run_id == run.id).one()

    now = datetime.now(timezone.utc)

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

    assert result == {"requeued": 1, "failed": 0}
    assert job.status == "queued"
    assert job.locked_by is None
    assert job.lease_expires_at is None
    assert job.heartbeat_at is None
    assert job.available_at > now

def test_expired_job_fails_after_max_attempts(db, run):
    job = db.query(Job).filter(Job.run_id == run.id).one()

    now = datetime.now(timezone.utc)

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

    assert result == {"requeued": 0, "failed": 1}
    assert job.status == "failed"
    assert job.locked_by is None
    assert job.lease_expires_at is None
