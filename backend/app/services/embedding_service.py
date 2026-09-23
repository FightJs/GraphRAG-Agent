"""OpenRouter embedding client — SPEC-VECTOR Stage4/query vectorization."""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# qwen3-embedding-8b outputs 4096-dim vectors
DEFAULT_DIM = 4096


def embedding_available(api_key: str | None) -> bool:
    return bool(api_key)


async def embed_texts(api_key: str, texts: list[str], model: str | None = None) -> list[list[float]]:
    """Embed a batch of texts. Returns one vector per input text."""
    if not texts:
        return []
    payload = {
        "model": model or settings.OPENROUTER_EMBEDDING_MODEL,
        "input": texts,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.OPENROUTER_BASE_URL}/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    items = data.get("data") or []
    items = sorted(items, key=lambda x: x.get("index", 0))
    vectors = [item.get("embedding") or [] for item in items]
    if len(vectors) != len(texts):
        raise ValueError(f"embedding count mismatch: got {len(vectors)} for {len(texts)} texts")
    return vectors


async def embed_query(api_key: str, text: str, model: str | None = None) -> list[float]:
    vecs = await embed_texts(api_key, [text], model=model)
    return vecs[0]
