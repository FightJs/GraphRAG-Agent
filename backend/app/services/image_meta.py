"""图片解析公共工具 — caption 兼容、meta 契约、final_text 组装"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import settings

SCHEMA_VERSION = "image-v1"


def extract_caption(block: dict) -> tuple[str, str]:
    """兼容 img_caption（字符串）与 image_caption（数组）两种形态。

    返回 (caption_raw, caption_source)
    """
    img_caption = block.get("img_caption")
    if isinstance(img_caption, str) and img_caption.strip():
        return img_caption.strip(), "img_caption"
    if isinstance(img_caption, list):
        joined = " ".join(str(x).strip() for x in img_caption if str(x).strip())
        if joined:
            return joined, "img_caption"

    image_caption = block.get("image_caption")
    if isinstance(image_caption, str) and image_caption.strip():
        return image_caption.strip(), "image_caption"
    if isinstance(image_caption, list):
        joined = " ".join(str(x).strip() for x in image_caption if str(x).strip())
        if joined:
            return joined, "image_caption"

    # 官方规范字段名也可能是 image_caption
    return "", "empty"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def empty_side() -> dict:
    return {"status": "skipped", "text": ""}


def empty_route() -> dict:
    return {
        "decision": "skip",
        "confidence": 0.0,
        "reason": "not_routed",
        "image_kind": "unknown",
        "model": "none",
        "latency_ms": 0,
        "fallback": False,
    }


def build_meta(
    *,
    image_id: str,
    doc_id: str,
    page_idx: Any,
    bbox: Any,
    img_path: str,
    origin_relpath: str,
    caption_raw: str,
    caption_source: str,
    route: dict | None = None,
    ocr: dict | None = None,
    describe: dict | None = None,
    final_text: str = "",
    final_kind: str = "empty",
    status: str = "ok",
    error: str | None = None,
) -> dict:
    ocr_block = ocr or empty_side()
    describe_block = describe or empty_side()
    # 双侧 status 必须齐全
    ocr_block.setdefault("status", "skipped")
    ocr_block.setdefault("text", "")
    describe_block.setdefault("status", "skipped")
    describe_block.setdefault("text", "")
    route_block = route or empty_route()
    return {
        "schema_version": SCHEMA_VERSION,
        "image_id": image_id,
        "doc_id": doc_id,
        "page_idx": page_idx,
        "bbox": bbox,
        "img_path": img_path,
        "origin_relpath": origin_relpath,
        "caption_raw": caption_raw,
        "caption_source": caption_source,
        "route": route_block,
        "ocr": ocr_block,
        "describe": describe_block,
        "final_text": final_text,
        "final_kind": final_kind,
        "status": status,
        "error": error,
        "created_at": utc_now_iso(),
    }


def assemble_final_text(
    ocr: dict | None,
    describe: dict | None,
    caption_raw: str,
    *,
    min_ocr_chars: int | None = None,
    min_ocr_conf: float | None = None,
) -> tuple[str, str, bool]:
    """按 SPEC §5.2 组装 final_text。返回 (final_text, final_kind, fallback_used)。

    OCR 成功但文本过短/低置信时，若 describe 成功则采用 describe 并标记 fallback。
    """
    min_ocr_chars = settings.MIN_OCR_CHARS if min_ocr_chars is None else min_ocr_chars
    min_ocr_conf = settings.OCR_MIN_AVG_CONFIDENCE if min_ocr_conf is None else min_ocr_conf

    ocr = ocr or {}
    describe = describe or {}
    ocr_text = (ocr.get("text") or "").strip()
    desc_text = (describe.get("text") or "").strip()
    ocr_ok = ocr.get("status") == "ok" and len(ocr_text) >= min_ocr_chars
    ocr_conf = ocr.get("avg_confidence")
    ocr_good = ocr_ok and (ocr_conf is None or ocr_conf >= min_ocr_conf)
    desc_ok = describe.get("status") == "ok" and desc_text

    fallback = False
    if ocr_good:
        return ocr_text, "ocr_text", False
    if ocr.get("status") == "ok" and ocr_text and not ocr_good and desc_ok:
        # 路由选了 OCR 但质量差（过短/低置信），MAY 采用 describe 并标记 fallback
        return desc_text, "description", True
    if ocr.get("status") == "ok" and ocr_text and not ocr_ok:
        # 有文本但过短；若 describe 不可用仍可短暂采用 OCR 文本
        if not desc_ok:
            return ocr_text, "ocr_text", False
    if desc_ok:
        # OCR 未成功或不可用时采用 describe
        if ocr.get("status") in ("ok", "failed"):
            fallback = True
        return desc_text, "description", fallback
    if caption_raw:
        return caption_raw, "caption_only", False
    return "", "empty", False


def _field_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        parts = [str(item).strip() for item in value if item is not None and str(item).strip()]
        return " ".join(parts)
    return str(value).strip()


def page_context_from_blocks(content_list: list[dict], page_idx: Any, max_chars: int = 300) -> str:
    """取同页 text block 前 max_chars 作为可选上下文。"""
    if page_idx is None:
        return ""
    parts: list[str] = []
    total = 0
    for block in content_list or []:
        if not isinstance(block, dict):
            continue
        if block.get("page_idx") != page_idx:
            continue
        if block.get("type") != "text":
            continue
        text = _field_text(block.get("content")) or _field_text(block.get("text"))
        if not text:
            continue
        parts.append(text)
        total += len(text)
        if total >= max_chars:
            break
    joined = "\n".join(parts)
    return joined[:max_chars]
