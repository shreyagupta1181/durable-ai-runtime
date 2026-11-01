from typing import Any, Callable

from pydantic import BaseModel, ValidationError


class Tool:
    def __init__(
        self,
        name: str,
        description: str,
        input_schema: type[BaseModel],
        function: Callable,
    ):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.function = function


class ToolRegistry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")

        self.tools[tool.name] = tool

    def get_tool(self, name: str) -> Tool:
        tool = self.tools.get(name)

        if tool is None:
            raise ValueError(f"Unknown tool: {name}")

        return tool

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        tool = self.get_tool(name)

        try:
            validated_arguments = tool.input_schema(**arguments)

        except ValidationError as exc:
            raise ValueError(
                f"Invalid arguments for tool '{name}': {exc}"
            ) from exc

        return tool.function(**validated_arguments.model_dump())