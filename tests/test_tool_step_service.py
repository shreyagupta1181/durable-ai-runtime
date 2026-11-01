
from app.models.tool_step import ToolStep
from app.services.tool_step_service import (
    get_or_create_step,
    complete_step,
    get_completed_step,
    claim_tool_step,
    renew_tool_step_lease,
    fail_tool_step,
)
from datetime import datetime, timezone, timedelta
import pytest


def test_create_and_retrieve_tool_step(db, run):
    step = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:0",
        tool_name="calculator",
        arguments={"expression": "100 + 50"},
    )

    assert step.status == "pending"
    assert step.tool_name == "calculator"
    assert step.arguments == {"expression": "100 + 50"}

    retrieved = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:0",
        tool_name="calculator",
        arguments={"expression": "100 + 50"},
    )

    assert retrieved.id == step.id


def test_completed_step_stores_result(db, run):
    step = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:1",
        tool_name="calculator",
        arguments={"expression": "100 + 50"},
    )

    claim_tool_step(db, step.id, "worker-1")

    complete_step(
        db=db,
        step_id=step.id,
        worker_id="worker-1",
        result={"value": 150},
    )

    db.refresh(step)

    assert step.status == "completed"
    assert step.result == {"value": 150}
    assert step.claimed_by is None
    assert step.lease_expires_at is None


def test_completed_step_can_be_retrieved(db, run):
    step = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:2",
        tool_name="calculator",
        arguments={"expression": "20 * 5"},
    )

    claim_tool_step(db, step.id, "worker-1")

    complete_step(
        db=db,
        step_id=step.id,
        worker_id="worker-1",
        result={"value": 100},
    )

    retrieved = get_completed_step(
        db=db,
        run_id=run.id,
        step_key="calculator:2",
    )

    assert retrieved is not None
    assert retrieved.result == {"value": 100}


def test_incomplete_step_is_not_retrieved(db, run):
    get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:3",
        tool_name="calculator",
        arguments={"expression": "10 + 10"},
    )

    retrieved = get_completed_step(
        db=db,
        run_id=run.id,
        step_key="calculator:3",
    )

    assert retrieved is None


def test_pending_step_can_be_claimed(db, run):
    step = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:4",
        tool_name="calculator",
        arguments={"expression": "10 + 20"},
    )

    claimed = claim_tool_step(
        db=db,
        step_id=step.id,
        worker_id="worker-1",
    )

    assert claimed.status == "running"
    assert claimed.claimed_by == "worker-1"
    assert claimed.lease_expires_at is not None
    assert claimed.attempts == 1


def test_active_step_cannot_be_claimed_by_another_worker(db, run):
    step = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:5",
        tool_name="calculator",
        arguments={"expression": "10 + 20"},
    )

    claim_tool_step(db, step.id, "worker-1")

    second_claim = claim_tool_step(
        db=db,
        step_id=step.id,
        worker_id="worker-2",
    )

    assert second_claim is None


def test_expired_step_can_be_reclaimed(db, run):
    step = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:6",
        tool_name="calculator",
        arguments={"expression": "10 + 20"},
    )

    claim_tool_step(db, step.id, "worker-1")

    step = db.query(ToolStep).filter(ToolStep.id == step.id).one()
    step.lease_expires_at = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    db.commit()

    reclaimed = claim_tool_step(
        db=db,
        step_id=step.id,
        worker_id="worker-2",
    )

    assert reclaimed.status == "running"
    assert reclaimed.claimed_by == "worker-2"
    assert reclaimed.attempts == 2


def test_completed_step_is_not_claimed_again(db, run):
    step = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:7",
        tool_name="calculator",
        arguments={"expression": "10 + 20"},
    )

    claim_tool_step(db, step.id, "worker-1")

    complete_step(
        db=db,
        step_id=step.id,
        worker_id="worker-1",
        result={"value": 30},
    )

    claimed = claim_tool_step(
        db=db,
        step_id=step.id,
        worker_id="worker-2",
    )

    assert claimed.status == "completed"
    assert claimed.result == {"value": 30}
    assert claimed.attempts == 1


def test_wrong_worker_cannot_complete_step(db, run):
    step = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:8",
        tool_name="calculator",
        arguments={"expression": "5 + 5"},
    )

    claim_tool_step(db, step.id, "worker-1")

    with pytest.raises(ValueError, match="does not own"):
        complete_step(
            db=db,
            step_id=step.id,
            worker_id="worker-2",
            result={"value": 10},
        )


def test_expired_lease_cannot_complete_step(db, run):
    step = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:9",
        tool_name="calculator",
        arguments={"expression": "5 + 5"},
    )

    claim_tool_step(db, step.id, "worker-1")

    step = db.query(ToolStep).filter(ToolStep.id == step.id).one()
    step.lease_expires_at = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    db.commit()

    with pytest.raises(ValueError, match="lease has expired"):
        complete_step(
            db=db,
            step_id=step.id,
            worker_id="worker-1",
            result={"value": 10},
        )


def test_worker_can_renew_own_lease(db, run):
    step = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:10",
        tool_name="calculator",
        arguments={"expression": "10 + 20"},
    )

    claimed = claim_tool_step(db, step.id, "worker-1")
    original_expiry = claimed.lease_expires_at

    renewed = renew_tool_step_lease(
        db=db,
        step_id=step.id,
        worker_id="worker-1",
        lease_duration_seconds=60,
    )

    assert renewed.lease_expires_at > original_expiry
    assert renewed.claimed_by == "worker-1"


def test_another_worker_cannot_renew_lease(db, run):
    step = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:11",
        tool_name="calculator",
        arguments={"expression": "10 + 20"},
    )

    claim_tool_step(db, step.id, "worker-1")

    with pytest.raises(ValueError, match="does not own"):
        renew_tool_step_lease(
            db=db,
            step_id=step.id,
            worker_id="worker-2",
        )


def test_expired_lease_cannot_be_renewed(db, run):
    step = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:12",
        tool_name="calculator",
        arguments={"expression": "10 + 20"},
    )

    claim_tool_step(db, step.id, "worker-1")

    step = db.query(ToolStep).filter(ToolStep.id == step.id).one()
    step.lease_expires_at = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    db.commit()

    with pytest.raises(ValueError, match="lease has expired"):
        renew_tool_step_lease(
            db=db,
            step_id=step.id,
            worker_id="worker-1",
        )


def test_worker_can_fail_own_step(db, run):
    step = get_or_create_step(
        db, run.id, "step-fail-1", "calculator", {"a": 1}
    )

    claim_tool_step(db, step.id, "worker-1")

    failed = fail_tool_step(
        db, step.id, "worker-1", "Division by zero"
    )

    assert failed.status == "failed"
    assert failed.error == "Division by zero"
    assert failed.claimed_by is None
    assert failed.lease_expires_at is None


def test_another_worker_cannot_fail_step(db, run):
    step = get_or_create_step(
        db, run.id, "step-fail-2", "calculator", {"a": 1}
    )

    claim_tool_step(db, step.id, "worker-1")

    with pytest.raises(ValueError, match="does not own"):
        fail_tool_step(
            db, step.id, "worker-2", "Some error"
        )


def test_expired_lease_cannot_fail_step(db, run):
    step = get_or_create_step(
        db, run.id, "step-fail-3", "calculator", {"a": 1}
    )

    claimed = claim_tool_step(db, step.id, "worker-1")

    claimed.lease_expires_at = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    db.commit()

    with pytest.raises(ValueError, match="lease has expired"):
        fail_tool_step(
            db, step.id, "worker-1", "Some error"
        )
