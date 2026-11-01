
import threading
from functools import lru_cache

from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY, GEMINI_MODEL
from app.db.database import SessionLocal
from app.services.tool_step_service import (
    get_or_create_step,
    claim_tool_step,
    renew_tool_step_lease,
    complete_step,fail_tool_step
)


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



def execute_durable_tool(
    db,
    run_id,
    worker_id,
    registry,
    tool_name,
    arguments,
    step_key,
):
    """Execute a tool with persistent step tracking and lease renewal."""

    step = get_or_create_step(
        db=db,
        run_id=run_id,
        step_key=step_key,
        tool_name=tool_name,
        arguments=arguments,
    )

    # Reuse completed results.
    if step.status == "completed":
        return step.result

    # A failed step is not automatically retried.
    if step.status == "failed":
        raise RuntimeError(
            f"Tool step {step_key} has already failed: {step.error}"
        )

    claimed = claim_tool_step(
        db=db,
        step_id=step.id,
        worker_id=worker_id,
    )

    if claimed is None:
        raise RuntimeError(
            f"Tool step {step_key} is owned by another worker."
        )

    if claimed.status == "completed":
        return claimed.result

    stop_heartbeat = threading.Event()
    lease_lost = threading.Event()

    def heartbeat():
        while not stop_heartbeat.wait(10):
            try:
                with SessionLocal() as heartbeat_db:
                    renew_tool_step_lease(
                        db=heartbeat_db,
                        step_id=step.id,
                        worker_id=worker_id,
                    )

            except Exception as exc:
                print(
                    f"Tool-step heartbeat failed for {step.id}: {exc}",
                    flush=True,
                )
                lease_lost.set()
                return

    heartbeat_thread = threading.Thread(
        target=heartbeat,
        daemon=True,
    )

    heartbeat_thread.start()

    try:
        result = registry.execute(tool_name, arguments)

        if lease_lost.is_set():
            raise RuntimeError(
                f"Lost lease while executing tool step {step_key}."
            )

        complete_step(
            db=db,
            step_id=step.id,
            worker_id=worker_id,
            result=result,
        )

        return result

    except Exception as exc:

        # Do not modify the step if this worker has lost its lease.
        if not lease_lost.is_set():
            try:
                fail_tool_step(
                    db=db,
                    step_id=step.id,
                    worker_id=worker_id,
                    error=str(exc),
                )

            except Exception as failure_exc:
                print(
                    f"Could not persist tool-step failure "
                    f"for {step.id}: {failure_exc}",
                    flush=True,
                )

        raise

    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=2)

def generate_agent_response(
    task: str,
    registry,
    db,
    run_id,
    worker_id: str,
    max_tool_rounds: int = 5,
    event_callback=None,
) -> str:
    """Let Gemini select and execute registered tools durably."""

    if not task or not task.strip():
        raise ValueError("Task cannot be empty.")

    client = get_gemini_client()

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

        for call_index, function_call in enumerate(response.function_calls):

            tool_name = function_call.name
            arguments = dict(function_call.args or {})
            call_id = function_call.id

            step_key = f"round:{tool_rounds}:call:{call_index}"

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
                result = execute_durable_tool(
                    db=db,
                    run_id=run_id,
                    worker_id=worker_id,
                    registry=registry,
                    tool_name=tool_name,
                    arguments=arguments,
                    step_key=step_key,
                )

                tool_response = {"result": result}

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

            except (ValueError, TypeError) as exc:

                tool_response = {"error": str(exc)}

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

            function_responses.append(
                types.Part.from_function_response(
                    name=tool_name,
                    response=tool_response,
                )
            )

        response = chat.send_message(function_responses)
        tool_rounds += 1

    answer = response.text

    if not answer or not answer.strip():
        raise RuntimeError("Gemini returned an empty response.")

    answer = answer.strip()

    if event_callback:
        event_callback(
            "agent_response_generated",
            {"response": answer},
        )

    return answer
