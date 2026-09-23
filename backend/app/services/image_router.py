"""VLM 图片路由 — 决定走 OCR / 描述 / skip（SPEC §6）"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

from app.config import settings
from app.services import vlm_client

logger = logging.getLogger(__name__)

VALID_DECISIONS = {"ocr", "describe", "skip"}
OCR_KINDS = {"screenshot", "table_image"}
DESCRIBE_KINDS = {"chart", "diagram", "photo", "mixed"}
SKIP_KINDS = {"logo", "decorative"}
VALID_KINDS = OCR_KINDS | DESCRIBE_KINDS | SKIP_KINDS | {"unknown"}

_HEURISTIC_DESC_KEYWORDS = ("图", "架构", "流程", "示意", "拓扑", "时序", "类图", "框图", "图表")

_ROUTE_SYSTEM = """你是图片路由引擎。根据图片内容判断后续处理方式，只输出 JSON，不要输出任何多余文字。
JSON 格式：
{"decision":"ocr|describe|skip","confidence":0.0,"image_kind":"screenshot|chart|diagram|photo|table_image|logo|decorative|mixed|unknown","reason":"一句话"}
决策规则：
- 密集文字截图、表格截图 → ocr，image_kind=screenshot 或 table_image
- 图表、示意图、架构图、照片、混合信息图 → describe，image_kind 对应 chart/diagram/photo/mixed
- logo、纯装饰、小图标 → skip，image_kind 对应 logo/decorative
confidence 为 0-1 的置信度。"""


@dataclass
class RouteDecision:
    decision: str  # ocr | describe | skip
    confidence: float
    image_kind: str
    reason: str
    model: str
    latency_ms: int
    fallback: bool = False

    def to_meta(self) -> dict:
        return {
            "decision": self.decision,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "image_kind": self.image_kind,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "fallback": self.fallback,
        }


def heuristic_route(caption: str, width: int, height: int) -> RouteDecision:
    """无 VLM Key 或 VLM 失败时的降级启发式路由。"""
    cap = caption or ""
    if width and height and (
        width < settings.IMAGE_MIN_SIDE_PX or height < settings.IMAGE_MIN_SIDE_PX
    ):
        return RouteDecision(
            decision="skip",
            confidence=0.9,
            image_kind="decorative",
            reason="尺寸过小，按装饰图跳过",
            model="heuristic",
            latency_ms=0,
        )
    if any(k in cap for k in _HEURISTIC_DESC_KEYWORDS):
        return RouteDecision(
            decision="describe",
            confidence=0.6,
            image_kind="diagram",
            reason="caption 含图/架构/流程等关键词，启发式走描述",
            model="heuristic",
            latency_ms=0,
        )
    return RouteDecision(
        decision="ocr",
        confidence=0.5,
        image_kind="unknown",
        reason="无 VLM Key，默认先 OCR，失败再回退 caption",
        model="heuristic",
        latency_ms=0,
    )


def _parse_route_json(content: str) -> dict | None:
    content = (content or "").strip()
    if not content:
        return None
    # 直接 JSON
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # 截取首个 {...}
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _coerce_decision(data: dict) -> RouteDecision | None:
    decision = str(data.get("decision") or "").strip().lower()
    kind = str(data.get("image_kind") or "unknown").strip().lower()
    if decision not in VALID_DECISIONS:
        return None
    if kind not in VALID_KINDS:
        kind = "unknown"
    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    reason = str(data.get("reason") or "").strip()[:200]
    return RouteDecision(
        decision=decision,
        confidence=confidence,
        image_kind=kind,
        reason=reason,
        model="",
        latency_ms=0,
    )


def apply_decision_rules(decision: RouteDecision) -> RouteDecision:
    """按 SPEC §6.4 对 kind 与置信度做硬约束。"""
    min_conf = settings.MEDIA_ROUTE_MIN_CONFIDENCE
    if decision.image_kind in SKIP_KINDS:
        return decision
    if decision.confidence < min_conf and decision.decision != "skip":
        # 低置信：先 OCR，质量差再描述（由 final_text/服务层补跑）
        return decision
    if decision.image_kind in OCR_KINDS:
        decision.decision = "ocr"
    elif decision.image_kind in DESCRIBE_KINDS:
        decision.decision = "describe"
    return decision


async def route(
    image_bytes: bytes,
    caption: str,
    page_context: str,
    vlm_key: str | None,
    *,
    width: int = 0,
    height: int = 0,
    mime: str = "image/png",
) -> RouteDecision:
    """主路径：单次 VLM 分类；无 Key/失败时启发式降级。"""
    if not vlm_key:
        return heuristic_route(caption, width, height)

    prompt_parts = ["请判断这张图片应如何处理。"]
    if caption:
        prompt_parts.append(f"页面 caption：{caption[:200]}")
    if page_context:
        prompt_parts.append(f"同页文本摘要：{page_context[:200]}")
    prompt = "\n".join(prompt_parts)

    started = time.perf_counter()
    try:
        content, used_model = await vlm_client.vision_chat(
            vlm_key,
            image_bytes=image_bytes,
            prompt=prompt,
            mime=mime,
            max_tokens=200,
            temperature=0.2,
            system=_ROUTE_SYSTEM,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        data = _parse_route_json(content)
        if data is None:
            logger.info("VLM 路由输出非 JSON，降级启发式")
            return heuristic_route(caption, width, height)
        decision = _coerce_decision(data)
        if decision is None:
            return heuristic_route(caption, width, height)
        decision.model = used_model
        decision.latency_ms = latency_ms
        decision = apply_decision_rules(decision)
        # 极低置信且非 skip：标记低置信，由后续 OCR 失败补跑 describe
        if decision.confidence < settings.MEDIA_ROUTE_MIN_CONFIDENCE and decision.decision != "skip":
            decision.reason = (decision.reason + "；低置信")[:200]
        return decision
    except Exception as exc:
        logger.warning("VLM 路由失败，降级启发式: %s", exc)
        return heuristic_route(caption, width, height)
