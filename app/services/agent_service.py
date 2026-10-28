from sqlalchemy.orm import Session

from app.services.llm_service import generate_response
from app.services.run_service import get_run


def execute_agent(db: Session, run_id) -> str:
    """Execute a task using the LLM and return its response."""

    run = get_run(db, run_id)

    if run is None:
        raise ValueError(f"Run {run_id} not found.")

    

    from app.models.event import RunEvent

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

    return generate_response(task)