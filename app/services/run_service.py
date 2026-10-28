import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.run import Run
from app.models.event import RunEvent
from app.models.job import Job


def create_run(db: Session, task: str) -> Run:
    """Create a run, its initial event, and its job atomically."""

    try:
        now = datetime.now(timezone.utc)

        run = Run(
            id=uuid.uuid4(),
            status="pending",
            created_at=now,
        )

        db.add(run)
        db.flush()

        event = RunEvent(
            id=uuid.uuid4(),
            run_id=run.id,
            seq=1,
            type="run_created",
            payload={
                "status": "pending",
                "task": task,
            },
            timestamp=now,
        )

        job = Job(
            id=uuid.uuid4(),
            run_id=run.id,
            status="queued",
            attempts=0,
            max_attempts=3,
            available_at=now,
            locked_by=None,
            locked_at=None,
        )

        db.add(event)
        db.add(job)

        db.commit()
        db.refresh(run)

        return run

    except Exception:
        db.rollback()
        raise


def get_run(db: Session, run_id: uuid.UUID) -> Run | None:
    """Fetch a run by its ID."""

    return db.get(Run, run_id)


ALLOWED_TRANSITIONS = {
    "pending": {"running", "cancelled"},
    "running": {"waiting_approval", "retrying", "succeeded", "failed"},
    "retrying": {"running", "cancelled", "failed"},
    "waiting_approval": {"running", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}


def transition_run(
    db: Session,
    run_id: uuid.UUID,
    new_status: str,
) -> Run:
    """Change a run's status and record the transition atomically."""

    try:
        run = (
            db.query(Run)
            .filter(Run.id == run_id)
            .with_for_update()
            .first()
        )

        if run is None:
            raise ValueError("Run not found")

        old_status = run.status

        if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
            raise ValueError(
                f"Invalid transition: {old_status} -> {new_status}"
            )

        last_seq = (
            db.query(RunEvent.seq)
            .filter(RunEvent.run_id == run_id)
            .order_by(RunEvent.seq.desc())
            .first()
        )

        next_seq = (last_seq[0] if last_seq else 0) + 1

        run.status = new_status

        event = RunEvent(
            id=uuid.uuid4(),
            run_id=run_id,
            seq=next_seq,
            type="run_status_changed",
            payload={
                "from": old_status,
                "to": new_status,
            },
            timestamp=datetime.now(timezone.utc),
        )

        db.add(event)
        db.commit()
        db.refresh(run)

        return run

    except Exception:
        db.rollback()
        raise