
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
