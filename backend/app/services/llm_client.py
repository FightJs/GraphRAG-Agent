"""DeepSeek LLM 客户端 — OpenAI 兼容 Chat Completions 接口"""
import json
from typing import AsyncGenerator, Optional

import httpx

from app.config import settings


def llm_available(api_key: str) -> bool:
    return bool(api_key)


async def chat_complete(api_key: str, messages: list[dict], temperature: float = 0.2, max_tokens: int = 2048,
                         response_format_json: bool = False) -> tuple[str, dict]:
    """非流式调用，返回 (content, {input_tokens, output_tokens})"""
    payload: dict = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if response_format_json:
        payload["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, {
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }


async def chat_stream(api_key: str, messages: list[dict], temperature: float = 0.3, max_tokens: int = 2048) -> AsyncGenerator[dict, None]:
    """流式调用，逐个 yield {"delta": str} 或最终 {"done": True, "usage": {...}}"""
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    input_tokens_est = sum(len(m["content"]) for m in messages) // 2
    output_chars = 0
    async with httpx.AsyncClient(timeout=90.0) as client:
        async with client.stream(
            "POST",
            f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                chunk = json.loads(raw)
                delta = chunk["choices"][0]["delta"].get("content")
                if delta:
                    output_chars += len(delta)
                    yield {"delta": delta}
    yield {"done": True, "usage": {"input_tokens": input_tokens_est, "output_tokens": output_chars}}
