
import uuid
from datetime import datetime, timezone,timedelta

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
def claim_tool_step(
    db: Session,
    step_id: uuid.UUID,
    worker_id: str,
    lease_duration_seconds: int = 30,
) -> ToolStep | None:
    if not worker_id or not worker_id.strip():
        raise ValueError("worker_id cannot be empty.")

    if lease_duration_seconds <= 0:
        raise ValueError("Lease duration must be positive.")

    try:
        step = (
            db.query(ToolStep)
            .filter(ToolStep.id == step_id)
            .with_for_update()
            .one_or_none()
        )

        if step is None:
            raise ValueError("Tool step not found.")

        now = datetime.now(timezone.utc)

        if step.status == "completed":
            db.commit()
            return step

        if step.status == "running" and step.lease_expires_at is not None:
            if step.lease_expires_at > now:
                if step.claimed_by != worker_id:
                    db.commit()
                    return None

                db.commit()
                return step

        if step.status not in ("pending", "running"):
            db.commit()
            return None

        step.status = "running"
        step.claimed_by = worker_id
        step.lease_expires_at = now + timedelta(
            seconds=lease_duration_seconds
        )
        step.attempts += 1
        step.updated_at = now

        db.commit()
        db.refresh(step)
        return step

    except Exception:
        db.rollback()
        raise
def renew_tool_step_lease(
    db: Session,
    step_id: uuid.UUID,
    worker_id: str,
    lease_duration_seconds: int = 30,
) -> ToolStep:
    """Extend a tool-step lease if the worker still owns a valid lease."""

    if not worker_id or not worker_id.strip():
        raise ValueError("worker_id cannot be empty.")

    if lease_duration_seconds <= 0:
        raise ValueError("Lease duration must be positive.")

    try:
        step = (
            db.query(ToolStep)
            .filter(ToolStep.id == step_id)
            .with_for_update()
            .one()
        )

        now = datetime.now(timezone.utc)

        if step.status != "running":
            raise ValueError(
                f"Cannot renew lease for step with status '{step.status}'."
            )

        if step.claimed_by != worker_id:
            raise ValueError("Worker does not own this tool step.")

        if step.lease_expires_at is None or step.lease_expires_at <= now:
            raise ValueError("Tool step lease has expired.")

        step.lease_expires_at = now + timedelta(
            seconds=lease_duration_seconds
        )
        step.updated_at = now

        db.commit()
        db.refresh(step)

        return step

    except Exception:
        db.rollback()
        raise

def complete_step(
    db: Session,
    step_id: uuid.UUID,
    worker_id: str,
    result,
) -> ToolStep:
    """Complete a tool step only if the worker owns a valid lease."""

    if not worker_id or not worker_id.strip():
        raise ValueError("worker_id cannot be empty.")

    try:
        step = (
            db.query(ToolStep)
            .filter(ToolStep.id == step_id)
            .with_for_update()
            .one()
        )

        # Idempotency: never overwrite an already completed result.
        if step.status == "completed":
            db.commit()
            return step

        now = datetime.now(timezone.utc)

        if step.status != "running":
            raise ValueError(
                f"Cannot complete step with status '{step.status}'."
            )

        if step.claimed_by != worker_id:
            raise ValueError("Worker does not own this tool step.")

        if step.lease_expires_at is None or step.lease_expires_at <= now:
            raise ValueError("Tool step lease has expired.")

        step.result = result
        step.status = "completed"
        step.error = None
        step.claimed_by = None
        step.lease_expires_at = None
        step.updated_at = now

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

def fail_tool_step(
    db: Session,
    step_id: uuid.UUID,
    worker_id: str,
    error: str,
) -> ToolStep:
    """Mark a tool step as failed if the worker owns a valid lease."""

    if not worker_id or not worker_id.strip():
        raise ValueError("worker_id cannot be empty.")

    try:
        step = (
            db.query(ToolStep)
            .filter(ToolStep.id == step_id)
            .with_for_update()
            .one()
        )

        now = datetime.now(timezone.utc)

        if step.status != "running":
            raise ValueError(
                f"Cannot fail step with status '{step.status}'."
            )

        if step.claimed_by != worker_id:
            raise ValueError("Worker does not own this tool step.")

        if step.lease_expires_at is None or step.lease_expires_at <= now:
            raise ValueError("Tool step lease has expired.")

        step.status = "failed"
        step.error = error
        step.claimed_by = None
        step.lease_expires_at = None
        step.updated_at = now

        db.commit()
        db.refresh(step)

        return step

    except Exception:
        db.rollback()
        raise