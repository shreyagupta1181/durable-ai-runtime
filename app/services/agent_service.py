
from sqlalchemy.orm import Session

from app.models.event import RunEvent
from app.services.event_service import append_event
from app.services.llm_service import generate_agent_response
from app.services.run_service import get_run
from app.tools import create_default_registry


def execute_agent(db: Session, run_id) -> str:
    """Execute an agent task and persist its execution events."""

    run = get_run(db, run_id)

    if run is None:
        raise ValueError(f"Run {run_id} not found.")

    created_event = (
        db.query(RunEvent)
        .filter(
            RunEvent.run_id == run_id,
            RunEvent.type == "run_created",
        )
        .order_by(RunEvent.seq.asc())
        .first()
    )

    if created_event is None:
        raise ValueError("The run has no run_created event.")

    task = created_event.payload.get("task")

    if not isinstance(task, str) or not task.strip():
        raise ValueError("The run does not contain a valid task.")

    def record_event(event_type: str, payload: dict) -> None:
        append_event(
            db=db,
            run_id=run_id,
            event_type=event_type,
            payload=payload,
        )

    record_event(
        "agent_started",
        {"task": task},
    )

    registry = create_default_registry()

    return generate_agent_response(
        task=task,
        registry=registry,
        event_callback=record_event,
    )
