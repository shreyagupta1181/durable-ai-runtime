from app.core.tool_registry import Tool, ToolRegistry
from app.tools.calculator import CalculatorInput, calculate


def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(
        Tool(
            name="calculator",
            description="Evaluates basic mathematical expressions.",
            input_schema=CalculatorInput,
            function=calculate,
        )
    )

    return registry