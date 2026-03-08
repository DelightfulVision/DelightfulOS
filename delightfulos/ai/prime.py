"""Prime Intellect inference client — OpenAI-compatible API with team billing.

Also provides K2 Think V2 client (separate MBZUAI/IFM API).
"""
from openai import AsyncOpenAI
from delightfulos.ai.config import settings

_client: AsyncOpenAI | None = None
_k2_client: AsyncOpenAI | None = None


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


def get_k2_client() -> AsyncOpenAI:
    """Get the K2 Think V2 client (MBZUAI/IFM API)."""
    global _k2_client
    if _k2_client is None:
        _k2_client = AsyncOpenAI(
            api_key=settings.k2_api_key,
            base_url=settings.k2_base_url,
        )
    return _k2_client


def _is_k2_model(model: str | None) -> bool:
    return model is not None and "k2" in model.lower()


async def list_models() -> list[dict]:
    models = []
    resp = await get_client().models.list()
    models.extend({"id": m.id, "owned_by": m.owned_by} for m in resp.data)
    # Add K2 Think V2 if configured
    if settings.k2_api_key:
        models.append({"id": settings.k2_model, "owned_by": "MBZUAI-IFM"})
    return models


async def chat(
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.7,
) -> str:
    if _is_k2_model(model):
        resp = await get_k2_client().chat.completions.create(
            model=model or settings.k2_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    else:
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
    if _is_k2_model(model):
        stream = await get_k2_client().chat.completions.create(
            model=model or settings.k2_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
    else:
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
