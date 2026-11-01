
from functools import lru_cache

from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY, GEMINI_MODEL


@lru_cache(maxsize=1)
def get_gemini_client() -> genai.Client:
    """Create and reuse one Gemini client."""

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is missing. Add it to your .env file."
        )

    return genai.Client(api_key=GEMINI_API_KEY)


def generate_response(task: str) -> str:
    """Send a task to Gemini and return its text response."""

    if not task or not task.strip():
        raise ValueError("Task cannot be empty.")

    client = get_gemini_client()

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=task,
    )

    answer = response.text

    if not answer or not answer.strip():
        raise RuntimeError("Gemini returned an empty response.")

    return answer.strip()


def generate_agent_response(
    task: str,
    registry,
    max_tool_rounds: int = 5,
    event_callback=None,
) -> str:
    """Let Gemini select and execute registered tools."""

    if not task or not task.strip():
        raise ValueError("Task cannot be empty.")

    client = get_gemini_client()

    # Convert registered tools into Gemini function declarations.
    function_declarations = []

    for tool in registry.tools.values():
        function_declarations.append(
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters=tool.input_schema.model_json_schema(),
            )
        )

    if not function_declarations:
        raise ValueError("No tools are registered.")

    gemini_tool = types.Tool(
        function_declarations=function_declarations
    )

    # Our runtime, not Gemini, executes the functions.
    config = types.GenerateContentConfig(
        tools=[gemini_tool],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            disable=True
        ),
    )

    chat = client.chats.create(
        model=GEMINI_MODEL,
        config=config,
    )

    response = chat.send_message(task)

    tool_rounds = 0

    while response.function_calls:

        if tool_rounds >= max_tool_rounds:
            raise RuntimeError(
                "Maximum tool-calling rounds exceeded."
            )

        function_responses = []

        for function_call in response.function_calls:

            tool_name = function_call.name
            arguments = dict(function_call.args or {})
            call_id = function_call.id

            print(
                f"Gemini requested tool: {tool_name}",
                flush=True,
            )

            if event_callback:
                event_callback(
                    "tool_call_requested",
                    {
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "call_id": call_id,
                    },
                )

            try:
                result = registry.execute(
                    tool_name,
                    arguments,
                )

            except (ValueError, TypeError) as exc:

                tool_response = {
                    "error": str(exc),
                }

                if event_callback:
                    event_callback(
                        "tool_execution_failed",
                        {
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "error": str(exc),
                            "call_id": call_id,
                        },
                    )

            else:

                tool_response = {
                    "result": result,
                }

                if event_callback:
                    event_callback(
                        "tool_execution_completed",
                        {
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "result": result,
                            "call_id": call_id,
                        },
                    )

            function_responses.append(
                types.Part.from_function_response(
                    name=tool_name,
                    response=tool_response,
                )
            )

        # Return the tool results to Gemini.
        response = chat.send_message(function_responses)

        tool_rounds += 1

    answer = response.text

    if not answer or not answer.strip():
        raise RuntimeError(
            "Gemini returned an empty response."
        )

    answer = answer.strip()

    if event_callback:
        event_callback(
            "agent_response_generated",
            {
                "response": answer,
            },
        )

    return answer
