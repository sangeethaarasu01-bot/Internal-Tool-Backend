"""SSE helpers for LLM token streaming."""

from collections.abc import Awaitable, Callable

from app.llm.client import LLMClient


async def stream_completion(
    llm: LLMClient,
    system: str,
    user: str,
    on_token: Callable[[str], Awaitable[None] | None],
) -> str:
    resp = await llm.stream(system, user, on_token)
    return resp.text
