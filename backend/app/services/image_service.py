"""图片智能解析主服务 — 落盘后路由/OCR/描述，写 meta 并挂到 KG"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from app.config import settings
from app.services import image_asset_service, image_describer, image_meta, image_ocr, image_router, media_store
from app.services.image_asset_service import ImageAsset
from app.services.image_describer import DescriptionResult
from app.services.image_ocr import OcrResult
from app.services.image_router import RouteDecision

logger = logging.getLogger(__name__)


def make_image_id(doc_id: str, seq: int) -> str:
    return image_asset_service.make_image_id(doc_id, seq)


def meta_path(doc_id: str, image_id: str) -> Path:
    return media_store.image_meta_path(doc_id, image_id)


def _relative_media_path(doc_id: str, image_id: str, ext: str) -> str:
    return f"media/{doc_id}/images/{image_id}.{ext}"


def _mime_from_ext(ext: str) -> str:
    ext = (ext or "").lower()
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    if ext == "webp":
        return "image/webp"
    if ext == "bmp":
        return "image/bmp"
    return "image/png"


def _as_path_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(str(x).strip() for x in value if x is not None and str(x).strip())
    return str(value).strip()


def _write_meta(doc_id: str, image_id: str, meta: dict) -> None:
    path = meta_path(doc_id, image_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


class _VlmBudget:
    """单文档 VLM 调用预算（路由与描述共享）。"""

    def __init__(self, max_calls: int):
        self._sem = asyncio.Semaphore(max(1, settings.VLM_CONCURRENCY))
        self._left = max_calls
        self._lock = asyncio.Lock()

    async def try_call(self, coro_factory):
        """在预算与并发限制下执行一次 VLM 调用。预算耗尽或无 Key 时返回 None。"""
        async with self._lock:
            if self._left <= 0:
                return None
            self._left -= 1
        async with self._sem:
            return await coro_factory()


async def _run_route(
    vlm_bytes: bytes,
    caption_raw: str,
    page_context: str,
    vlm_key: str | None,
    *,
    width: int,
    height: int,
    budget: _VlmBudget | None,
) -> RouteDecision:
    if not vlm_key:
        return image_router.heuristic_route(caption_raw, width, height)

    async def _call():
        return await image_router.route(
            vlm_bytes, caption_raw, page_context, vlm_key,
            width=width, height=height, mime="image/png",
        )

    if budget is None:
        return await _call()
    result = await budget.try_call(_call)
    if result is None:
        return image_router.heuristic_route(caption_raw, width, height)
    return result


async def _run_describe(
    vlm_bytes: bytes,
    caption_raw: str,
    page_context: str,
    vlm_key: str | None,
    budget: _VlmBudget | None,
) -> DescriptionResult:
    if not vlm_key:
        return DescriptionResult(status="failed", error="缺少 OpenRouter API Key")

    async def _call():
        return await image_describer.describe(
            vlm_bytes, caption_raw, page_context, vlm_key
        )

    if budget is None:
        return await _call()
    result = await budget.try_call(_call)
    if result is None:
        return DescriptionResult(status="skipped", error="VLM 配额耗尽")
    return result


async def _process_one(
    *,
    doc_id: str,
    seq: int,
    block: dict,
    content_list: list[dict],
    assets: dict[str, ImageAsset],
    vlm_key: str | None,
    budget: _VlmBudget | None,
) -> dict:
    image_id = image_asset_service.make_image_id(doc_id, seq)
    caption_raw, caption_source = image_meta.extract_caption(block)
    page_idx = block.get("page_idx")
    bbox = block.get("bbox")
    asset = assets.get(image_id)
    page_context = image_meta.page_context_from_blocks(content_list, page_idx)

    if asset is None:
        meta = image_meta.build_meta(
            image_id=image_id,
            doc_id=doc_id,
            page_idx=page_idx,
            bbox=bbox,
            img_path="",
            origin_relpath=block.get("img_path") or "",
            caption_raw=caption_raw,
            caption_source=caption_source,
            status="missing_asset",
            error="图片文件缺失",
        )
        if caption_raw:
            meta["final_text"] = caption_raw
            meta["final_kind"] = "caption_only"
        _write_meta(doc_id, image_id, meta)
        return meta

    origin_relpath = asset.origin_relpath or (block.get("img_path") or "")
    img_path_rel = _relative_media_path(doc_id, image_id, asset.ext)

    if image_asset_service.is_too_small(asset.width, asset.height):
        meta = image_meta.build_meta(
            image_id=image_id,
            doc_id=doc_id,
            page_idx=page_idx,
            bbox=bbox,
            img_path=img_path_rel,
            origin_relpath=origin_relpath,
            caption_raw=caption_raw,
            caption_source=caption_source,
            status="skipped",
            final_text=caption_raw,
            final_kind="caption_only" if caption_raw else "empty",
        )
        meta["route"] = {
            **image_meta.empty_route(),
            "decision": "skip",
            "confidence": 0.95,
            "reason": "尺寸过小",
            "image_kind": "decorative",
            "model": "heuristic",
        }
        _write_meta(doc_id, image_id, meta)
        return meta

    image_bytes = image_asset_service.read_image_bytes(asset.local_path)
    vlm_bytes = image_asset_service.resize_for_vlm(image_bytes)
    mime = _mime_from_ext(asset.ext)

    route_decision = await _run_route(
        vlm_bytes, caption_raw, page_context, vlm_key,
        width=asset.width, height=asset.height, budget=budget,
    )

    ocr_result = OcrResult(status="skipped")
    desc_result = DescriptionResult(status="skipped")
    status = "ok"
    error: str | None = None

    if route_decision.decision == "skip":
        pass
    elif route_decision.decision == "ocr":
        ocr_result = image_ocr.run(image_bytes)
        need_fallback = (
            ocr_result.status != "ok"
            or len((ocr_result.text or "").strip()) < settings.MIN_OCR_CHARS
            or (ocr_result.avg_confidence or 0) < settings.OCR_MIN_AVG_CONFIDENCE
        )
        if need_fallback and vlm_key:
            desc_result = await _run_describe(
                vlm_bytes, caption_raw, page_context, vlm_key, budget
            )
            if desc_result.status == "ok":
                route_decision.fallback = True
        if ocr_result.status != "ok" and desc_result.status != "ok" and not caption_raw:
            status = "failed"
            error = ocr_result.error or "OCR 失败且无 caption"
    elif route_decision.decision == "describe":
        desc_result = await _run_describe(
            vlm_bytes, caption_raw, page_context, vlm_key, budget
        )
        if desc_result.status == "failed" and vlm_key is None:
            # 无 VLM Key 的启发式 describe：改跑 OCR
            ocr_result = image_ocr.run(image_bytes)
            route_decision.fallback = True
        elif desc_result.status == "failed":
            # 描述失败 → 回退 caption（§8.3）
            pass

    final_text, final_kind, text_fallback = image_meta.assemble_final_text(
        image_ocr.to_meta_block(ocr_result),
        image_describer.to_meta_block(desc_result),
        caption_raw,
    )
    if text_fallback:
        route_decision.fallback = True

    meta = image_meta.build_meta(
        image_id=image_id,
        doc_id=doc_id,
        page_idx=page_idx,
        bbox=bbox,
        img_path=img_path_rel,
        origin_relpath=origin_relpath,
        caption_raw=caption_raw,
        caption_source=caption_source,
        route=route_decision.to_meta(),
        ocr=image_ocr.to_meta_block(ocr_result),
        describe=image_describer.to_meta_block(desc_result),
        final_text=final_text,
        final_kind=final_kind,
        status=status,
        error=error,
    )
    _write_meta(doc_id, image_id, meta)
    return meta


async def process_all(
    doc_id: str,
    content_list: list[dict],
    *,
    vlm_key: str | None = None,
    zip_bytes: bytes | None = None,
) -> list[dict]:
    """处理文档全部 image block，返回 meta 列表（按 seq 顺序）。"""
    image_blocks = image_asset_service.iter_image_blocks(content_list)
    if not image_blocks:
        return []

    assets = image_asset_service.ensure_zip_assets(doc_id, content_list, zip_bytes)

    # 路由与描述各算一次；单文档上限 VLM_MAX_IMAGES_PER_DOC 张（§14）
    budget = _VlmBudget(settings.VLM_MAX_IMAGES_PER_DOC * 2) if vlm_key else None

    async def worker(seq: int, block: dict) -> dict:
        return await _process_one(
            doc_id=doc_id,
            seq=seq,
            block=block,
            content_list=content_list,
            assets=assets,
            vlm_key=vlm_key,
            budget=budget,
        )

    tasks = [asyncio.create_task(worker(i, b)) for i, b in enumerate(image_blocks)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metas: list[dict] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("图片处理异常 seq=%s: %s", i, result)
            caption_raw, caption_source = image_meta.extract_caption(image_blocks[i])
            image_id = image_asset_service.make_image_id(doc_id, i)
            meta = image_meta.build_meta(
                image_id=image_id,
                doc_id=doc_id,
                page_idx=image_blocks[i].get("page_idx"),
                bbox=image_blocks[i].get("bbox"),
                img_path="",
                origin_relpath=_as_path_text(image_blocks[i].get("img_path")),
                caption_raw=caption_raw,
                caption_source=caption_source,
                status="failed",
                error=str(result),
                final_text=caption_raw,
                final_kind="caption_only" if caption_raw else "empty",
            )
            _write_meta(doc_id, image_id, meta)
            metas.append(meta)
        else:
            metas.append(result)
    return metas


async def process_images(
    doc_id: str,
    content_list: list[dict],
    zip_bytes: bytes | None,
    vlm_key: str | None,
    original_name: str = "",
) -> list[dict]:
    """索引管线入口（与 table_service.process_tables 对齐）。"""
    return await process_all(doc_id, content_list, vlm_key=vlm_key, zip_bytes=zip_bytes)


def image_node_label(meta: dict, seq: int) -> str:
    caption = (meta.get("caption_raw") or "").strip()
    if caption:
        return caption
    page_idx = meta.get("page_idx")
    if isinstance(page_idx, int):
        return f"第{page_idx + 1}页图片#{seq}"
    return meta.get("image_id") or f"图片#{seq}"


def attach_to_kg(kg: dict, metas: list[dict], doc_id: str | None = None, original_name: str = "") -> dict:
    """向 KG 写入 DOCUMENT 根节点（如无）、IMAGE 节点与 HAS_IMAGE 边。

    - IMAGE 仅流水线写入；重建时按 media_id 幂等覆盖
    - label 优先级：caption_raw → 第{page+1}页图片#{seq} → image_id
    - HAS_IMAGE 确定性 id：image_edge_{doc8}_{seq4}
    """
    kg = kg or {}
    if not doc_id:
        doc_id = kg.get("doc_id") or (metas[0].get("doc_id") if metas else "")
    kg = media_store.ensure_document_node(kg, doc_id, original_name)
    doc_node_id = media_store.find_document_node_id(kg, doc_id) or f"doc_{media_store.doc8(doc_id)}"
    doc8 = media_store.doc8(doc_id)

    nodes = kg.get("nodes") or []
    edges = kg.get("edges") or []

    # 清理旧 IMAGE 节点与关联边（幂等重建）
    old_image_ids = {n.get("id") for n in nodes if n.get("type") == "IMAGE"}
    kg["nodes"] = [n for n in nodes if n.get("type") != "IMAGE"]
    kg["edges"] = [
        e
        for e in edges
        if e.get("source") not in old_image_ids
        and e.get("target") not in old_image_ids
        and not str(e.get("id", "")).startswith("image_edge_")
    ]

    nodes = kg["nodes"]
    edges = kg["edges"]
    existing_node_ids = {n.get("id") for n in nodes}
    existing_edge_ids = {e.get("id") for e in edges}

    for seq, meta in enumerate(metas):
        if not meta:
            continue
        status = meta.get("status")
        final_text = (meta.get("final_text") or "").strip()
        if status == "failed" and not final_text:
            continue
        if status == "skipped" and not final_text:
            continue
        image_id = meta.get("image_id") or f"img_{doc8}_{seq:04d}"
        node_id = f"image_{doc8}_{seq:04d}"
        if node_id in existing_node_ids:
            node_id = f"image_{doc8}_{seq:04d}_{uuid.uuid4().hex[:6]}"
        existing_node_ids.add(node_id)

        route_decision = (meta.get("route") or {}).get("decision") or ""
        image_kind = (meta.get("route") or {}).get("image_kind") or ""
        summary = final_text[:200]
        node = {
            "id": node_id,
            "label": image_node_label(meta, seq),
            "type": "IMAGE",
            "attributes": {
                "media_id": image_id,
                "page_idx": meta.get("page_idx"),
                "route": route_decision,
                "image_kind": image_kind,
                "final_kind": meta.get("final_kind"),
                "summary": summary,
                "source_ref": f"{{{{IMAGE:{image_id}}}}}",
            },
        }
        nodes.append(node)

        edge_id = f"image_edge_{doc8}_{seq:04d}"
        if edge_id in existing_edge_ids:
            edge_id = str(uuid.uuid4())
        existing_edge_ids.add(edge_id)
        edges.append(
            {
                "id": edge_id,
                "source": doc_node_id,
                "target": node_id,
                "relation": "HAS_IMAGE",
            }
        )

    meta_block = dict(kg.get("meta") or {})
    meta_block["total_nodes"] = len(nodes)
    meta_block["total_edges"] = len(edges)
    meta_block["image_count"] = sum(1 for n in nodes if n.get("type") == "IMAGE")
    kg["meta"] = meta_block
    return kg


def load_all_metas(doc_id: str) -> list[dict]:
    dir_path = image_asset_service.images_dir(doc_id)
    if not dir_path.exists():
        return []
    metas: list[dict] = []
    for path in sorted(dir_path.glob("*.meta.json")):
        try:
            metas.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return metas
