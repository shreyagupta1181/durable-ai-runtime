import random
import uuid

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.event import RunEvent
from app.models.job import Job
from app.models.run import Run
from app.services.run_service import ALLOWED_TRANSITIONS


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
    job_id: uuid.UUID,
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


def renew_job_lease(
    db: Session,
    job_id: uuid.UUID,
    worker_id: str,
) -> bool:
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


def complete_job(
    db: Session,
    job_id: uuid.UUID,
    worker_id: str,
) -> bool:
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
def complete_job_and_run(
    db: Session,
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    worker_id: str,
) -> bool:
    """
    Atomically mark a job and its run as succeeded.

    Both changes and the run-status event are committed together.
    """
    now = datetime.now(timezone.utc)

    try:
        # 1. Lock the job and verify lease ownership.
        job = (
            db.query(Job)
            .filter(
                Job.id == job_id,
                Job.run_id == run_id,
                Job.status == "running",
                Job.locked_by == worker_id,
                Job.lease_expires_at > now,
            )
            .with_for_update()
            .one_or_none()
        )

        if job is None:
            db.rollback()
            return False

        # 2. Lock the associated run.
        run = (
            db.query(Run)
            .filter(Run.id == run_id)
            .with_for_update()
            .one_or_none()
        )

        if run is None:
            raise ValueError(f"Run {run_id} not found")

        old_status = run.status

        # 3. Validate the run transition.
        if "succeeded" not in ALLOWED_TRANSITIONS.get(old_status, set()):
            raise ValueError(
                f"Invalid transition: {old_status} -> succeeded"
            )

        # 4. Update the job.
        job.status = "succeeded"
        job.locked_by = None
        job.locked_at = None
        job.heartbeat_at = None
        job.lease_expires_at = None
        job.updated_at = now

        # 5. Update the run.
        run.status = "succeeded"

        # 6. Allocate the next event sequence number.
        last_seq = (
            db.query(RunEvent.seq)
            .filter(RunEvent.run_id == run_id)
            .order_by(RunEvent.seq.desc())
            .first()
        )

        next_seq = (last_seq[0] if last_seq else 0) + 1

        # 7. Record the status transition.
        db.add(
            RunEvent(
                id=uuid.uuid4(),
                run_id=run_id,
                seq=next_seq,
                type="run_status_changed",
                payload={
                    "from": old_status,
                    "to": "succeeded",
                },
                timestamp=now,
            )
        )

        # 8. Commit everything atomically.
        db.commit()

        return True

    except Exception:
        db.rollback()
        raise


def handle_job_failure(
    db: Session,
    job_id: uuid.UUID,
    worker_id: str,
    error: str,
) -> str:
    """
    Handle a job failure.

    Requeue the job if attempts remain; otherwise, mark it failed.
    Return the resulting job status.
    """
    now = datetime.now(timezone.utc)

    try:
        # Lock the job and verify that this worker still owns it.
        job = (
            db.query(Job)
            .filter(
                Job.id == job_id,
                Job.status == "running",
                Job.locked_by == worker_id,
                Job.lease_expires_at > now,
            )
            .with_for_update()
            .one_or_none()
        )

        if job is None:
            db.rollback()
            return "lease_lost"

        # Lock the associated run.
        run = (
            db.query(Run)
            .filter(Run.id == job.run_id)
            .with_for_update()
            .one_or_none()
        )

        if run is None:
            raise ValueError(f"Run {job.run_id} not found")

        old_run_status = run.status

        if job.attempts < job.max_attempts:
            # Retry with exponential backoff and random jitter.
            delay = min(2 ** job.attempts, 60)
            delay += random.uniform(0, 1)

            job.status = "queued"
            job.available_at = now + timedelta(seconds=delay)

            if run.status == "running":
                run.status = "retrying"

            result_status = "queued"
            event_type = "job_requeued"

            payload = {
                "job_id": str(job.id),
                "attempts": job.attempts,
                "max_attempts": job.max_attempts,
                "retry_delay_seconds": round(delay, 2),
                "reason": "execution_error",
                "error": error,
            }

        else:
            job.status = "failed"

            if run.status in {"running", "retrying"}:
                run.status = "failed"

            result_status = "failed"
            event_type = "job_failed"

            payload = {
                "job_id": str(job.id),
                "attempts": job.attempts,
                "max_attempts": job.max_attempts,
                "reason": "attempts_exhausted",
                "error": error,
            }

        # Release the lease.
        job.locked_by = None
        job.locked_at = None
        job.heartbeat_at = None
        job.lease_expires_at = None
        job.updated_at = now

        # Allocate event sequence numbers while holding the run lock.
        last_seq = (
            db.query(RunEvent.seq)
            .filter(RunEvent.run_id == run.id)
            .order_by(RunEvent.seq.desc())
            .first()
        )

        next_seq = (last_seq[0] if last_seq else 0) + 1

        db.add(
            RunEvent(
                id=uuid.uuid4(),
                run_id=run.id,
                seq=next_seq,
                type=event_type,
                payload=payload,
                timestamp=now,
            )
        )

        # Record the run transition when its status changes.
        if old_run_status != run.status:
            db.add(
                RunEvent(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    seq=next_seq + 1,
                    type="run_status_changed",
                    payload={
                        "from": old_run_status,
                        "to": run.status,
                    },
                    timestamp=now,
                )
            )

        db.commit()
        return result_status

    except Exception:
        db.rollback()
        raise

def recover_expired_jobs(db: Session) -> dict[str, int]:
    """
    Recover jobs whose worker leases have expired.

    Jobs with attempts remaining are requeued with exponential backoff.
    Jobs that exhausted their attempts are marked failed.

    Job, run, and event changes are committed in one transaction.
    """
    now = datetime.now(timezone.utc)

    requeued = 0
    failed = 0

    try:
        statement = (
            select(Job)
            .where(
                Job.status == "running",
                Job.lease_expires_at.is_not(None),
                Job.lease_expires_at <= now,
            )
            .order_by(Job.lease_expires_at)
            .with_for_update(skip_locked=True)
        )

        expired_jobs = db.execute(statement).scalars().all()

        for job in expired_jobs:
            # Lock the associated run before updating it.
            run = (
                db.query(Run)
                .filter(Run.id == job.run_id)
                .with_for_update()
                .one_or_none()
            )

            if run is None:
                raise ValueError(
                    f"Run {job.run_id} not found for job {job.id}"
                )

            old_status = run.status

            # A terminal run must never be revived by recovery.
            if old_status in {"succeeded", "failed", "cancelled"}:
                if old_status == "succeeded":
                    job.status = "succeeded"
                elif old_status == "cancelled":
                    job.status = "cancelled"
                else:
                    job.status = "failed"

                job.locked_by = None
                job.locked_at = None
                job.heartbeat_at = None
                job.lease_expires_at = None
                job.updated_at = now

                continue

            if job.attempts < job.max_attempts:
                # Exponential backoff with random jitter.
                delay = min(2 ** job.attempts, 60)
                delay += random.uniform(0, 1)

                job.status = "queued"
                job.available_at = now + timedelta(seconds=delay)

                if old_status == "running":
                    run.status = "retrying"

                requeued += 1

                event_type = "job_requeued"
                payload = {
                    "job_id": str(job.id),
                    "attempts": job.attempts,
                    "max_attempts": job.max_attempts,
                    "retry_delay_seconds": round(delay, 2),
                    "reason": "lease_expired",
                }

            else:
                # The worker exhausted its allowed attempts.
                job.status = "failed"

                if old_status in {"running", "retrying"}:
                    run.status = "failed"

                failed += 1

                event_type = "job_failed"
                payload = {
                    "job_id": str(job.id),
                    "attempts": job.attempts,
                    "max_attempts": job.max_attempts,
                    "reason": "lease_expired_attempts_exhausted",
                }

            # Release the expired lease.
            job.locked_by = None
            job.locked_at = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            job.updated_at = now

            # The run row is locked, serializing event-sequence allocation
            # for this run against other code that follows the same lock rule.
            last_seq = (
                db.query(RunEvent.seq)
                .filter(RunEvent.run_id == run.id)
                .order_by(RunEvent.seq.desc())
                .first()
            )

            next_seq = (last_seq[0] if last_seq else 0) + 1

            # Record the recovery outcome.
            db.add(
                RunEvent(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    seq=next_seq,
                    type=event_type,
                    payload=payload,
                    timestamp=now,
                )
            )

            # Record the state transition if the run changed.
            if old_status != run.status:
                db.add(
                    RunEvent(
                        id=uuid.uuid4(),
                        run_id=run.id,
                        seq=next_seq + 1,
                        type="run_status_changed",
                        payload={
                            "from": old_status,
                            "to": run.status,
                        },
                        timestamp=now,
                    )
                )

        db.commit()

        return {
        "requeued": requeued,
        "failed": failed,
        }       

    except Exception:
        db.rollback()
        raise
