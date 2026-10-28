from functools import lru_cache

from google import genai

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