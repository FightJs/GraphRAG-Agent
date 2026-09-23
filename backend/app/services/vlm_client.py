"""OpenRouter Vision Chat 客户端 — SPEC §6.2 / §8"""
from __future__ import annotations

import base64
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class VlmError(Exception):
    pass


def encode_image_data_url(image_bytes: bytes, mime: str = "image/png") -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def vision_chat(
    api_key: str,
    *,
    image_bytes: bytes,
    prompt: str,
    mime: str = "image/png",
    max_tokens: int = 200,
    temperature: float = 0.2,
    model: str | None = None,
    system: str | None = None,
    timeout: float = 60.0,
) -> tuple[str, str]:
    """OpenAI 兼容 vision chat。返回 (content, model)。日志禁止完整 base64。"""
    if not api_key:
        raise VlmError("缺少 OpenRouter API Key")
    model_name = model or settings.VLM_MODEL
    data_url = encode_image_data_url(image_bytes, mime=mime)
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    )
    payload = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{settings.OPENROUTER_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            if resp.status_code >= 400:
                # 不记录 body 中可能的 base64
                raise VlmError(f"VLM HTTP {resp.status_code}")
            data = resp.json()
    except httpx.HTTPError as exc:
        raise VlmError(f"VLM 请求失败: {exc}") from exc

    choices = data.get("choices") or []
    if not choices:
        raise VlmError("VLM 响应缺少 choices")
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        # OpenRouter 有时返回 content parts
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    used_model = data.get("model") or model_name
    return str(content), str(used_model)
