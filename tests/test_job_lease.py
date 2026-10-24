from datetime import datetime, timedelta, timezone

from app.models.job import Job
from app.services.job_service import (
    claim_next_job,
    renew_job_lease,
)


def test_claim_creates_lease(db, run):
    job = db.query(Job).filter(Job.run_id == run.id).one()

    claimed = claim_next_job(db, "worker-1")

    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.locked_by == "worker-1"
    assert claimed.heartbeat_at is not None
    assert claimed.lease_expires_at is not None
    assert claimed.attempts == 1


def test_owner_can_renew_lease(db, run):
    job = db.query(Job).filter(Job.run_id == run.id).one()
    claimed = claim_next_job(db, "worker-1")

    assert claimed is not None

    old_expiry = claimed.lease_expires_at

    renewed = renew_job_lease(db, claimed.id, "worker-1")

    db.refresh(job)

    assert renewed is True
    assert job.lease_expires_at > old_expiry


def test_wrong_worker_cannot_renew_lease(db, run):
    claimed = claim_next_job(db, "worker-1")

    assert claimed is not None

    renewed = renew_job_lease(db, claimed.id, "worker-2")

    assert renewed is False
