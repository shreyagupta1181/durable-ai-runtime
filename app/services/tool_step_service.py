
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.tool_step import ToolStep


def get_or_create_step(
    db: Session,
    run_id: uuid.UUID,
    step_key: str,
    tool_name: str,
    arguments: dict,
) -> ToolStep:
    """Retrieve an existing step or create a new pending step."""

    statement = (
        insert(ToolStep)
        .values(
            id=uuid.uuid4(),
            run_id=run_id,
            step_key=step_key,
            tool_name=tool_name,
            arguments=arguments,
            status="pending",
        )
        .on_conflict_do_nothing(
            constraint="uq_tool_steps_run_id_step_key"
        )
        .returning(ToolStep.id)
    )

    try:
        db.execute(statement)
        db.commit()

        step = db.execute(
            select(ToolStep).where(
                ToolStep.run_id == run_id,
                ToolStep.step_key == step_key,
            )
        ).scalar_one()

        return step

    except Exception:
        db.rollback()
        raise


def complete_step(
    db: Session,
    step_id: uuid.UUID,
    result,
) -> ToolStep:
    """Persist a successful tool result."""

    try:
        step = (
            db.query(ToolStep)
            .filter(ToolStep.id == step_id)
            .with_for_update()
            .one()
        )

        if step.status == "completed":
            return step

        if step.status != "pending":
            raise ValueError(
                f"Cannot complete step with status '{step.status}'."
            )

        step.result = result
        step.status = "completed"
        step.error = None
        step.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(step)

        return step

    except Exception:
        db.rollback()
        raise


def get_completed_step(
    db: Session,
    run_id: uuid.UUID,
    step_key: str,
) -> ToolStep | None:
    """Retrieve a previously completed tool step."""

    return db.execute(
        select(ToolStep).where(
            ToolStep.run_id == run_id,
            ToolStep.step_key == step_key,
            ToolStep.status == "completed",
        )
    ).scalar_one_or_none()
