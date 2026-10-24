import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.job import Job


def claim_next_job(db: Session, worker_id: str) -> Job | None:
    """
    Claim the next available queued job.

    Returns the claimed job, or None if no job is available.
    """

    try:
        now = datetime.now(timezone.utc)

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
        job.attempts += 1

        db.commit()
        db.refresh(job)

        return job

    except Exception:
        db.rollback()
        raise