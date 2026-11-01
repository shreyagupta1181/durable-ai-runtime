
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.event import RunEvent
from app.models.run import Run


def append_event(
    db: Session,
    run_id: uuid.UUID,
    event_type: str,
    payload: dict,
) -> RunEvent:
    """Append an event with the next sequence number."""

    db.query(Run).filter(
        Run.id == run_id
    ).with_for_update().one()

    last_seq = (
        db.query(RunEvent.seq)
        .filter(RunEvent.run_id == run_id)
        .order_by(RunEvent.seq.desc())
        .first()
    )

    next_seq = (last_seq[0] if last_seq else 0) + 1

    event = RunEvent(
        id=uuid.uuid4(),
        run_id=run_id,
        seq=next_seq,
        type=event_type,
        payload=payload,
        timestamp=datetime.now(timezone.utc),
    )

    db.add(event)
    db.commit()
    db.refresh(event)

    return event
