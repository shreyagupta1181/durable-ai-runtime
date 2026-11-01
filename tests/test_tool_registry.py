import pytest
from pydantic import BaseModel, Field

from app.core.tool_registry import Tool, ToolRegistry


class AddInput(BaseModel):
    a: int = Field(ge=0)
    b: int = Field(ge=0)


def add(a: int, b: int) -> int:
    return a + b


def test_register_and_execute_tool():
    registry = ToolRegistry()

    tool = Tool(
        name="add",
        description="Adds two numbers.",
        input_schema=AddInput,
        function=add,
    )

    registry.register(tool)

    result = registry.execute(
        "add",
        {"a": 10, "b": 20},
    )

    assert result == 30


def test_unknown_tool():
    registry = ToolRegistry()

    with pytest.raises(ValueError, match="Unknown tool"):
        registry.execute("unknown", {})


def test_invalid_arguments():
    registry = ToolRegistry()

    registry.register(
        Tool(
            name="add",
            description="Adds two numbers.",
            input_schema=AddInput,
            function=add,
        )
    )

    with pytest.raises(ValueError, match="Invalid arguments"):
        registry.execute("add", {"a": -5, "b": 10})


def test_duplicate_registration():
    registry = ToolRegistry()

    tool = Tool(
        name="add",
        description="Adds two numbers.",
        input_schema=AddInput,
        function=add,
    )

    registry.register(tool)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(tool)