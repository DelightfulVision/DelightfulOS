"""Prime Intellect inference client — OpenAI-compatible API with team billing."""
from openai import AsyncOpenAI
from delightfulos.ai.config import settings

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        headers = {}
        if settings.prime_team_id:
            headers["X-Prime-Team-ID"] = settings.prime_team_id
        _client = AsyncOpenAI(
            api_key=settings.prime_api_key,
            base_url=settings.prime_base_url,
            default_headers=headers,
        )
    return _client


async def list_models() -> list[dict]:
    resp = await get_client().models.list()
    return [{"id": m.id, "owned_by": m.owned_by} for m in resp.data]


async def chat(
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.7,
) -> str:
    resp = await get_client().chat.completions.create(
        model=model or settings.model_quality,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


async def chat_stream(
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.7,
):
    stream = await get_client().chat.completions.create(
        model=model or settings.model_quality,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
