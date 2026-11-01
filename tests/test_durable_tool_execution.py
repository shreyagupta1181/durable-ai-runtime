
import pytest

from app.models.tool_step import ToolStep
from app.services.llm_service import execute_durable_tool


class FakeRegistry:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def execute(self, tool_name, arguments):
        self.calls += 1

        if self.error:
            raise self.error

        return self.result


def test_successful_tool_execution(db, run):
    registry = FakeRegistry(result={"value": 150})

    result = execute_durable_tool(
        db=db,
        run_id=run.id,
        worker_id="worker-1",
        registry=registry,
        tool_name="calculator",
        arguments={"expression": "100 + 50"},
        step_key="integration:success",
    )

    assert result == {"value": 150}
    assert registry.calls == 1

    step = (
        db.query(ToolStep)
        .filter(
            ToolStep.run_id == run.id,
            ToolStep.step_key == "integration:success",
        )
        .one()
    )

    assert step.status == "completed"
    assert step.result == {"value": 150}
    assert step.attempts == 1


def test_tool_execution_failure_is_persisted(db, run):
    registry = FakeRegistry(
        error=ValueError("Division by zero")
    )

    with pytest.raises(ValueError, match="Division by zero"):
        execute_durable_tool(
            db=db,
            run_id=run.id,
            worker_id="worker-1",
            registry=registry,
            tool_name="calculator",
            arguments={"expression": "10 / 0"},
            step_key="integration:failure",
        )

    step = (
        db.query(ToolStep)
        .filter(
            ToolStep.run_id == run.id,
            ToolStep.step_key == "integration:failure",
        )
        .one()
    )

    assert step.status == "failed"
    assert step.error == "Division by zero"
    assert step.claimed_by is None
    assert step.lease_expires_at is None
    assert registry.calls == 1


def test_completed_result_is_reused(db, run):
    first_registry = FakeRegistry(result={"value": 150})

    first_result = execute_durable_tool(
        db=db,
        run_id=run.id,
        worker_id="worker-1",
        registry=first_registry,
        tool_name="calculator",
        arguments={"expression": "100 + 50"},
        step_key="integration:reuse",
    )

    second_registry = FakeRegistry(result={"value": 999})

    second_result = execute_durable_tool(
        db=db,
        run_id=run.id,
        worker_id="worker-2",
        registry=second_registry,
        tool_name="calculator",
        arguments={"expression": "100 + 50"},
        step_key="integration:reuse",
    )

    assert first_result == {"value": 150}
    assert second_result == {"value": 150}

    assert first_registry.calls == 1
    assert second_registry.calls == 0


def test_execution_is_blocked_when_another_worker_owns_step(db, run):
    from app.services.tool_step_service import (
        get_or_create_step,
        claim_tool_step,
    )

    step = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="integration:ownership",
        tool_name="calculator",
        arguments={"expression": "10 + 20"},
    )

    claim_tool_step(
        db=db,
        step_id=step.id,
        worker_id="worker-1",
    )

    registry = FakeRegistry(result={"value": 30})

    with pytest.raises(RuntimeError, match="owned by another worker"):
        execute_durable_tool(
            db=db,
            run_id=run.id,
            worker_id="worker-2",
            registry=registry,
            tool_name="calculator",
            arguments={"expression": "10 + 20"},
            step_key="integration:ownership",
        )

    assert registry.calls == 0


def test_failed_step_is_not_executed_again(db, run):
    first_registry = FakeRegistry(
        error=ValueError("Invalid expression")
    )

    with pytest.raises(ValueError):
        execute_durable_tool(
            db=db,
            run_id=run.id,
            worker_id="worker-1",
            registry=first_registry,
            tool_name="calculator",
            arguments={"expression": "invalid"},
            step_key="integration:no-retry",
        )

    second_registry = FakeRegistry(result={"value": 100})

    with pytest.raises(RuntimeError, match="has already failed"):
        execute_durable_tool(
            db=db,
            run_id=run.id,
            worker_id="worker-2",
            registry=second_registry,
            tool_name="calculator",
            arguments={"expression": "invalid"},
            step_key="integration:no-retry",
        )

    assert first_registry.calls == 1
    assert second_registry.calls == 0
