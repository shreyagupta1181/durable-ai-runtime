from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.job import Job

LEASE_DURATION_SECONDS = 30


def claim_next_job(db: Session, worker_id: str) -> Job | None:
    """Claim the next available queued job and assign a lease."""
    now = datetime.now(timezone.utc)

    try:
        statement = (
            select(Job)
            .where(
                Job.status == "queued",
                Job.available_at <= now,
            )
            .order_by(Job.available_at, Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )

        job = db.execute(statement).scalar_one_or_none()

        if job is None:
            db.commit()
            return None

        job.status = "running"
        job.locked_by = worker_id
        job.locked_at = now
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(
            seconds=LEASE_DURATION_SECONDS
        )
        job.attempts += 1

        db.commit()
        db.refresh(job)
        return job

    except Exception:
        db.rollback()
        raise


def owns_valid_lease(
    db: Session,
    job_id,
    worker_id: str,
) -> bool:
    """Check whether this worker owns a currently valid lease."""
    now = datetime.now(timezone.utc)

    job = db.execute(
        select(Job.id).where(
            Job.id == job_id,
            Job.status == "running",
            Job.locked_by == worker_id,
            Job.lease_expires_at > now,
        )
    ).scalar_one_or_none()

    return job is not None


def renew_job_lease(db: Session, job_id, worker_id: str) -> bool:
    """Renew a lease only if the worker still owns a valid lease."""
    now = datetime.now(timezone.utc)

    try:
        result = db.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == "running",
                Job.locked_by == worker_id,
                Job.lease_expires_at > now,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=now + timedelta(
                    seconds=LEASE_DURATION_SECONDS
                ),
            )
        )

        db.commit()
        return result.rowcount == 1

    except Exception:
        db.rollback()
        raise


def complete_job(db: Session, job_id, worker_id: str) -> bool:
    """Complete a job only while the worker owns a valid lease."""
    now = datetime.now(timezone.utc)

    try:
        result = db.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == "running",
                Job.locked_by == worker_id,
                Job.lease_expires_at > now,
            )
            .values(
                status="succeeded",
                locked_by=None,
                locked_at=None,
                heartbeat_at=None,
                lease_expires_at=None,
                updated_at=now,
            )
        )

        db.commit()
        return result.rowcount == 1

    except Exception:
        db.rollback()
        raise
