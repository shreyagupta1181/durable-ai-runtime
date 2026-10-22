
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.run import Run
from app.models.event import RunEvent


def create_run(db: Session) -> Run:
    """Create a run and its initial event atomically."""

    run = Run(
        id=uuid.uuid4(),
        status="pending",
        created_at=datetime.now(timezone.utc),
    )

    db.add(run)
    db.flush()
    db.add(run)
    db.flush()
    print("Run ID after flush:", run.id)
    print("Run found in DB:", db.query(Run.id).filter(Run.id == run.id).first())

    event = RunEvent(
        id=uuid.uuid4(),
        run_id=run.id,
        seq=1,
        type="run_created",
        payload={"status": "pending"},
        timestamp=datetime.now(timezone.utc),
    )

    db.add(event)

    try:
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
    "running": {"waiting_approval", "succeeded", "failed"},
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
        # Lock this run so concurrent transitions don't overwrite each other.
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

        # Find the next event sequence number for this run.
        last_seq = (
            db.query(RunEvent.seq)
            .filter(RunEvent.run_id == run_id)
            .order_by(RunEvent.seq.desc())
            .with_for_update()
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

