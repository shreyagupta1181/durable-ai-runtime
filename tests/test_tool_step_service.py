
from app.models.tool_step import ToolStep
from app.services.tool_step_service import (
    get_or_create_step,
    complete_step,
    get_completed_step,
)


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

    complete_step(
        db=db,
        step_id=step.id,
        result={"value": 150},
    )

    db.refresh(step)

    assert step.status == "completed"
    assert step.result == {"value": 150}


def test_completed_step_can_be_retrieved(db, run):
    step = get_or_create_step(
        db=db,
        run_id=run.id,
        step_key="calculator:2",
        tool_name="calculator",
        arguments={"expression": "20 * 5"},
    )

    complete_step(
        db=db,
        step_id=step.id,
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
