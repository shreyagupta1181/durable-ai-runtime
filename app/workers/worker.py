
import time
import uuid

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.event import RunEvent
from app.models.job import Job
from app.models.run import Run
from app.services.job_service import (
    claim_next_job,
    complete_job,
    owns_valid_lease,
)
from app.services.run_service import transition_run


def append_event(
    db: Session,
    run_id: uuid.UUID,
    event_type: str,
    payload: dict,
) -> None:
    """Append an event using the next sequence number."""

    run = (
        db.query(Run)
        .filter(Run.id == run_id)
        .with_for_update()
        .one()
    )

    last_seq = (
        db.query(RunEvent.seq)
        .filter(RunEvent.run_id == run_id)
        .order_by(RunEvent.seq.desc())
        .first()
    )

    next_seq = (last_seq[0] if last_seq else 0) + 1

    db.add(
        RunEvent(
            id=uuid.uuid4(),
            run_id=run_id,
            seq=next_seq,
            type=event_type,
            payload=payload,
        )
    )
    db.commit()


def process_one_job(worker_id: str = "worker-1") -> bool:
    """Process one queued job."""

    with SessionLocal() as db:
        print("Checking for queued jobs...", flush=True)
        job = claim_next_job(db, worker_id)

        if job is None:
            print("No queued jobs found.", flush=True)
            return False

        job_id = job.id
        run_id = job.run_id

    print(f"Claimed job: {job_id}", flush=True)

    try:
        with SessionLocal() as db:
            transition_run(db, run_id, "running")

            append_event(
                db,
                run_id,
                "task_started",
                {"worker_id": worker_id},
            )

            # Placeholder until we implement the agent loop.
            result = {"message": "Hello from the worker!"}

            append_event(
                db,
                run_id,
                "task_completed",
                {"result": result},
            )

        # Check ownership before marking the run successful.
        with SessionLocal() as db:
            if not owns_valid_lease(db, job_id, worker_id):
                print(
                    f"Job {job_id}: lease expired or ownership was lost.",
                    flush=True,
                )
                return True

            # Complete the job first.
            if not complete_job(db, job_id, worker_id):
                print(
                    f"Job {job_id}: could not complete; lease lost.",
                    flush=True,
                )
                return True

        # Only now attempt the terminal run transition.
        with SessionLocal() as db:
            transition_run(db, run_id, "succeeded")

        print(f"Job {job_id} completed successfully.", flush=True)
        return True


    except Exception as exc:
        print(f"Job {job_id} failed: {exc}", flush=True)

        # Retry handling will be implemented separately.
        with SessionLocal() as db:
            job = db.get(Job, job_id)

            if (
                job is not None
                and job.status == "running"
                and job.locked_by == worker_id
            ):
                job.status = "failed"
                job.locked_by = None
                job.locked_at = None
                job.heartbeat_at = None
                job.lease_expires_at = None
                db.commit()

            run = db.get(Run, run_id)

            if run is not None and run.status == "running":
                try:
                    transition_run(db, run_id, "failed")
                except ValueError:
                    db.rollback()

        return True


def main() -> None:
    """Poll the database for queued jobs."""

    worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    print(f"Worker started: {worker_id}", flush=True)

    while True:
        processed = process_one_job(worker_id)

        if not processed:
            time.sleep(1)


if __name__ == "__main__":
    process_one_job("worker-test")
