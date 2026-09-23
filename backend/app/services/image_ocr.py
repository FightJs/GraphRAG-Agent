"""RapidOCR 单图识别 — SPEC §7"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)

_ocr_engine_cache = None


@dataclass
class OcrResult:
    engine: str = settings.OCR_ENGINE
    text: str = ""
    avg_confidence: float = 0.0
    status: str = "ok"  # ok | failed | skipped
    error: str | None = None
    detail: list = field(default_factory=list)


def _load_engine():
    """懒加载 RapidOCR，失败则返回 None。"""
    global _ocr_engine_cache
    if _ocr_engine_cache is not None:
        return _ocr_engine_cache or None
    try:
        from rapidocr import RapidOCR

        engine = RapidOCR()
        _ocr_engine_cache = engine
        return engine
    except Exception as exc:
        logger.warning("RapidOCR 加载失败: %s", exc)
        _ocr_engine_cache = False
        return None


def ocr_available() -> bool:
    return _load_engine() is not None


def normalize_ocr_text(text: str) -> str:
    """压缩空行、合并断行；不得改写数字与专有名词。"""
    if not text:
        return ""
    # 统一换行
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    # 去掉连续空行，保留段落分隔
    cleaned: list[str] = []
    blank = 0
    for ln in lines:
        if not ln.strip():
            blank += 1
            if blank <= 1:
                cleaned.append("")
            continue
        blank = 0
        cleaned.append(ln.strip())
    # 中文断行合并：上一行末尾是中文且下一行是中文/数字开头则拼接
    merged: list[str] = []
    cjk_end = re.compile(r"[一-鿿　-〿]$")
    cjk_start = re.compile(r"^[一-鿿0-9（(【]")
    for ln in cleaned:
        if not ln:
            merged.append(ln)
            continue
        if merged and merged[-1] and cjk_end.search(merged[-1]) and cjk_start.match(ln):
            merged[-1] = merged[-1] + ln
        else:
            merged.append(ln)
    return "\n".join(merged).strip()


def _result_from_rapidocr(raw) -> tuple[str, float, list]:
    """兼容 rapidocr v2/v3 返回结构：Result 对象或 (boxes, texts, scores) 元组。"""
    texts: list[str] = []
    scores: list[float] = []
    detail: list = []

    # v3 Result object
    if hasattr(raw, "txts") and hasattr(raw, "scores"):
        list_txts = list(raw.txts or [])
        list_scores = [float(s) for s in (raw.scores or [])]
        return "\n".join(t for t in list_txts if t), (
            sum(list_scores) / len(list_scores) if list_scores else 0.0
        ), list(zip(list_txts, list_scores))

    # v2 tuple: (boxes, txts, scores)
    if isinstance(raw, (tuple, list)) and len(raw) >= 3:
        txts = raw[1] or []
        scores_raw = raw[2] or []
        texts = [str(t) for t in txts]
        scores = [float(s) for s in scores_raw]
        detail = list(zip(texts, scores))
        avg = sum(scores) / len(scores) if scores else 0.0
        return "\n".join(t for t in texts if t), avg, detail

    # 单元素列表
    if isinstance(raw, (tuple, list)) and len(raw) == 1:
        return _result_from_rapidocr(raw[0])

    return "", 0.0, []


def run(image_bytes: bytes, engine: str | None = None) -> OcrResult:
    """对单张图片执行 OCR。异常不抛穿，返回 status=failed。"""
    engine_name = engine or settings.OCR_ENGINE
    eng = _load_engine()
    if eng is None:
        return OcrResult(engine=f"{engine_name}:unavailable", status="failed", error="OCR 引擎不可用")
    try:
        import io

        import numpy as np
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        if img.mode != "RGB":
            img = img.convert("RGB")
        # OCR 可使用原图；过小图做 1.5 倍放大提升可读性
        w, h = img.size
        if max(w, h) < 256:
            img = img.resize((int(w * 1.5), int(h * 1.5)), Image.Resampling.LANCZOS)
        arr = np.array(img)
        raw = eng(arr)
        if raw is None:
            return OcrResult(engine=engine_name, status="ok", text="", avg_confidence=0.0)
        text, avg_conf, detail = _result_from_rapidocr(raw)
        norm = normalize_ocr_text(text)
        return OcrResult(
            engine=f"{engine_name}:{settings.OCR_LANG}",
            text=norm,
            avg_confidence=avg_conf,
            status="ok",
            detail=detail,
        )
    except Exception as exc:
        logger.warning("OCR 执行失败: %s", exc)
        return OcrResult(engine=engine_name, status="failed", error=str(exc))


def to_meta_block(result: OcrResult) -> dict:
    return {
        "engine": result.engine,
        "text": result.text,
        "avg_confidence": round(result.avg_confidence, 4) if result.avg_confidence else 0.0,
        "status": result.status,
        "error": result.error,
    }
