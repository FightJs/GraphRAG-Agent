"""VLM 图片描述 — SPEC §8"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.config import settings
from app.services import vlm_client

logger = logging.getLogger(__name__)

_DESC_SYSTEM = """你是专业的图片描述引擎。根据图片内容生成中文、客观、可检索的描述。
要求：
1. 必须包含：画面中可见的文字、图表或示意图类型、主要信息或结论；
2. 禁止编造图中不存在的数据；
3. 长度控制在 80-300 汉字；
4. 只输出描述文本本身，不要前缀说明。"""


@dataclass
class DescriptionResult:
    text: str = ""
    status: str = "ok"  # ok | failed | skipped
    error: str | None = None
    model: str = ""
    latency_ms: int = 0


async def describe(
    image_bytes: bytes,
    caption: str,
    page_context: str,
    vlm_key: str | None,
    *,
    mime: str = "image/png",
) -> DescriptionResult:
    if not vlm_key:
        return DescriptionResult(status="failed", error="缺少 OpenRouter API Key")

    prompt_parts = ["请描述这张图片。"]
    if caption:
        prompt_parts.append(f"已知 caption：{caption[:200]}")
    if page_context:
        prompt_parts.append(f"同页文本摘要（仅供参考，不要照抄）：{page_context[:200]}")
    prompt = "\n".join(prompt_parts)

    started = time.perf_counter()
    try:
        content, used_model = await vlm_client.vision_chat(
            vlm_key,
            image_bytes=image_bytes,
            prompt=prompt,
            mime=mime,
            max_tokens=settings.IMAGE_DESC_MAX_TOKENS,
            temperature=0.2,
            system=_DESC_SYSTEM,
            timeout=90.0,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        text = (content or "").strip()
        if not text:
            return DescriptionResult(status="failed", error="VLM 返回空文本", model=used_model, latency_ms=latency_ms)
        return DescriptionResult(text=text, status="ok", model=used_model, latency_ms=latency_ms)
    except Exception as exc:
        logger.warning("VLM 描述失败: %s", exc)
        return DescriptionResult(status="failed", error=str(exc))


def to_meta_block(result: DescriptionResult) -> dict:
    return {
        "text": result.text if result.status == "ok" else "",
        "status": result.status,
        "error": result.error,
        "model": result.model,
        "latency_ms": result.latency_ms,
    }
