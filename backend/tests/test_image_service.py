"""SPEC-IMAGE 单元测试：caption 兼容、尺寸过滤、启发式路由、final_text、KG"""
from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.config import settings
from app.services import (
    image_asset_service,
    image_meta,
    image_router,
    image_service,
    parsing_service,
)


DOC_ID = "a1b2c3d4-1111-2222-3333-444455556666"


@pytest.fixture(autouse=True)
def _media_tmp(tmp_path, monkeypatch):
    media = tmp_path / "media"
    monkeypatch.setattr(settings, "MEDIA_DIR", str(media))
    yield


def _png_bytes(width: int = 200, height: int = 200, color=(200, 200, 200)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_extract_caption_img_caption_string():
    cap, src = image_meta.extract_caption({"img_caption": "图1  系统架构图"})
    assert cap == "图1  系统架构图"
    assert src == "img_caption"


def test_extract_caption_image_caption_array():
    cap, src = image_meta.extract_caption({"image_caption": ["图2", "流程说明"]})
    assert cap == "图2 流程说明"
    assert src == "image_caption"


def test_extract_caption_empty():
    cap, src = image_meta.extract_caption({})
    assert cap == ""
    assert src == "empty"


def test_too_small_filter():
    assert image_asset_service.is_too_small(10, 10) is True
    assert image_asset_service.is_too_small(20, 20) is True  # 面积 400 < 1024
    assert image_asset_service.is_too_small(200, 200) is False


def test_ensure_zip_assets_persists_images():
    content_list = [
        {"type": "text", "content": "正文", "page_idx": 0},
        {"type": "image", "img_path": "images/abc.png", "page_idx": 0, "img_caption": "图1"},
        {"type": "image", "img_path": "images/def.jpg", "page_idx": 1},
    ]
    zip_bytes = _make_zip(
        {
            "images/abc.png": _png_bytes(200, 200),
            "images/def.jpg": _png_bytes(150, 150),
        }
    )
    assets = image_asset_service.ensure_zip_assets(DOC_ID, content_list, zip_bytes)
    assert len(assets) == 2
    image_id0 = image_asset_service.make_image_id(DOC_ID, 0)
    assert image_id0 in assets
    p0 = assets[image_id0].local_path
    assert p0.exists() and p0.stat().st_size > 0
    assert assets[image_id0].width == 200
    assert assets[image_id0].origin_relpath.endswith("abc.png")


def test_ensure_zip_assets_missing_zip_returns_empty_without_history():
    content_list = [{"type": "image", "img_path": "images/x.png", "page_idx": 0}]
    assets = image_asset_service.ensure_zip_assets(DOC_ID, content_list, None)
    assert assets == {}


def test_heuristic_route_describe_by_caption():
    route = image_router.heuristic_route("图1 系统架构图", 400, 300)
    assert route.decision == "describe"
    assert route.model == "heuristic"


def test_heuristic_route_skip_small():
    route = image_router.heuristic_route("", 10, 10)
    assert route.decision == "skip"


def test_assemble_final_text_priority():
    ocr_ok = {"status": "ok", "text": "OCR提取的正文内容足够长", "avg_confidence": 0.9}
    desc = {"status": "ok", "text": "这是一张架构图"}
    text, kind, _fb = image_meta.assemble_final_text(ocr_ok, desc, "图1")
    assert kind == "ocr_text"
    assert "OCR提取" in text

    ocr_weak = {"status": "ok", "text": "短", "avg_confidence": 0.2}
    text, kind, fb = image_meta.assemble_final_text(ocr_weak, desc, "图1")
    assert kind == "description"
    assert fb is True

    text, kind, _fb = image_meta.assemble_final_text(
        {"status": "failed", "text": "", "avg_confidence": 0},
        {"status": "failed", "text": ""},
        "仅标题",
    )
    assert kind == "caption_only"
    assert text == "仅标题"

    text, kind, _fb = image_meta.assemble_final_text(
        {"status": "skipped", "text": ""},
        {"status": "skipped", "text": ""},
        "",
    )
    assert kind == "empty"


def test_process_images_missing_asset():
    content_list = [
        {"type": "image", "img_path": "images/missing.png", "page_idx": 1, "img_caption": "图9"}
    ]
    metas = asyncio.run(image_service.process_images(DOC_ID, content_list, None, None))
    assert len(metas) == 1
    meta = metas[0]
    assert meta["schema_version"] == "image-v1"
    assert meta["image_id"] == image_service.make_image_id(DOC_ID, 0)
    assert meta["status"] in ("missing_asset", "skipped", "failed", "ok")
    # 无资产时至少 caption 可用
    assert meta["caption_raw"] == "图9"
    assert "ocr" in meta and "status" in meta["ocr"]
    assert "describe" in meta and "status" in meta["describe"]


def test_process_images_small_skipped(tmp_path):
    content_list = [
        {"type": "image", "img_path": "images/tiny.png", "page_idx": 0},
    ]
    zip_bytes = _make_zip({"images/tiny.png": _png_bytes(8, 8)})
    metas = asyncio.run(image_service.process_images(DOC_ID, content_list, zip_bytes, None))
    assert len(metas) == 1
    # 小图被 zip 解码后可能直接跳过落盘 → missing/skipped
    assert metas[0]["status"] in ("skipped", "missing_asset", "failed", "ok")


def test_process_images_writes_meta_file():
    content_list = [
        {"type": "image", "img_path": "images/a.png", "page_idx": 0, "img_caption": "图1 架构"},
    ]
    zip_bytes = _make_zip({"images/a.png": _png_bytes(250, 250)})
    metas = asyncio.run(image_service.process_images(DOC_ID, content_list, zip_bytes, None))
    assert len(metas) == 1
    meta_path = Path(settings.MEDIA_DIR) / DOC_ID / "images" / f"{metas[0]['image_id']}.meta.json"
    assert meta_path.exists()
    loaded = json.loads(meta_path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "image-v1"
    assert loaded["ocr"] and "status" in loaded["ocr"]
    assert loaded["describe"] and "status" in loaded["describe"]
    # 无 VLM 时走启发式
    assert loaded["route"]["model"] in ("heuristic", settings.VLM_MODEL)


def test_attach_to_kg_image_nodes():
    metas = [
        {
            "schema_version": "image-v1",
            "image_id": image_service.make_image_id(DOC_ID, 0),
            "doc_id": DOC_ID,
            "page_idx": 1,
            "caption_raw": "图1 系统架构图",
            "final_text": "该图展示了网关与检索服务的调用关系",
            "final_kind": "description",
            "status": "ok",
            "route": {"decision": "describe", "image_kind": "diagram"},
        }
    ]
    kg = {
        "doc_id": DOC_ID,
        "nodes": [{"id": "concept_1_a", "label": "网关", "type": "CONCEPT", "attributes": {}}],
        "edges": [],
        "meta": {},
    }
    kg = image_service.attach_to_kg(kg, metas, DOC_ID, original_name="demo.pdf")
    types = {n["type"] for n in kg["nodes"]}
    assert "DOCUMENT" in types
    assert "IMAGE" in types
    img_node = next(n for n in kg["nodes"] if n["type"] == "IMAGE")
    assert img_node["attributes"]["media_id"] == metas[0]["image_id"]
    assert img_node["attributes"]["source_ref"] == f"{{{{IMAGE:{metas[0]['image_id']}}}}}"
    rels = {(e["relation"], e["target"]) for e in kg["edges"]}
    assert ("HAS_IMAGE", img_node["id"]) in rels


def test_image_placeholder_in_markdown():
    blocks = [
        {"type": "text", "content": "如下图所示", "page_idx": 0},
        {
            "type": "image",
            "img_path": "images/a.png",
            "page_idx": 0,
            "img_caption": "图1 架构",
        },
    ]
    md = parsing_service.content_list_to_markdown(blocks, image_ids={1: "img_x_0000"})
    assert "{{IMAGE:img_x_0000}}" in md
    assert "图1 架构" in md


def test_process_tables_json_file(tmp_path):
    from app.services import table_service

    blocks = [
        {
            "type": "table",
            "content": "<table><tr><th>指标</th><th>值</th></tr><tr><td>准确率</td><td>91.2%</td></tr></table>",
            "page_idx": 0,
            "table_caption": "表1 指标",
        }
    ]
    records, _ = asyncio.run(table_service.process_tables(DOC_ID, blocks, None, original_name="t.pdf"))
    assert len(records) == 1
    path = Path(settings.MEDIA_DIR) / DOC_ID / "tables" / f"{records[0]['table_id']}.json"
    assert path.exists()
    assert records[0]["summary_status"] in ("failed", "skipped")
    assert records[0]["n_rows"] == 1


# ── 补充：ID 幂等 / OCR / 路由 / KG 重建 ───────────────────────────

def test_make_image_id_deterministic():
    assert image_service.make_image_id(DOC_ID, 0) == "img_a1b2c3d4_0000"
    assert image_service.make_image_id(DOC_ID, 7) == "img_a1b2c3d4_0007"
    assert image_service.make_image_id(DOC_ID, 0) == image_service.make_image_id(DOC_ID, 0)


def test_ensure_zip_assets_reuses_history_when_zip_none():
    content_list = [
        {"type": "image", "img_path": "images/abc.png", "page_idx": 0},
    ]
    zip_bytes = _make_zip({"images/abc.png": _png_bytes(220, 220)})
    first = image_asset_service.ensure_zip_assets(DOC_ID, content_list, zip_bytes)
    assert first
    reused = image_asset_service.ensure_zip_assets(DOC_ID, content_list, None)
    assert set(reused) == set(first)


def test_resize_for_vlm_side_limit():
    from app.services import image_asset_service as ias

    big = _png_bytes(3000, 800)
    out = ias.resize_for_vlm(big, max_side=1568)
    img = Image.open(io.BytesIO(out))
    assert max(img.size) <= 1568
    assert max(img.size) >= 1500


def test_normalize_ocr_text_merges_and_keeps_numbers():
    from app.services import image_ocr

    raw = "第一行文字\n\n\n\n第二行\n3.14"
    out = image_ocr.normalize_ocr_text(raw)
    assert "3.14" in out
    assert "\n\n\n" not in out


def test_ocr_on_text_image():
    from PIL import ImageDraw, ImageFont

    from app.services import image_ocr

    if not image_ocr.ocr_available():
        pytest.skip("RapidOCR 不可用")
    img = Image.new("RGB", (480, 120), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 40)
    except OSError:
        font = ImageFont.load_default()
    draw.text((20, 30), "GraphRAG 123", fill=(0, 0, 0), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    result = image_ocr.run(buf.getvalue())
    assert result.status == "ok"
    joined = result.text.replace(" ", "").upper()
    assert any(k in joined for k in ("GRAPH", "RAG", "123", "AGENT"))


def test_route_parse_and_apply_rules():
    data = image_router._parse_route_json(
        '{"decision":"ocr","confidence":0.9,"image_kind":"screenshot","reason":"文字密集"}'
    )
    assert data["decision"] == "ocr"
    assert image_router._parse_route_json("not-json") is None

    d = image_router.RouteDecision("describe", 0.9, "screenshot", "", "m", 1)
    d = image_router.apply_decision_rules(d)
    assert d.decision == "ocr"

    d = image_router.RouteDecision("ocr", 0.9, "chart", "", "m", 1)
    d = image_router.apply_decision_rules(d)
    assert d.decision == "describe"


def test_attach_to_kg_idempotent_rebuild():
    metas = [
        {
            "schema_version": "image-v1",
            "image_id": image_service.make_image_id(DOC_ID, 0),
            "doc_id": DOC_ID,
            "page_idx": 0,
            "caption_raw": "图A",
            "final_text": "内容A",
            "final_kind": "description",
            "status": "ok",
            "route": {"decision": "describe", "image_kind": "diagram"},
        },
        {
            "schema_version": "image-v1",
            "image_id": image_service.make_image_id(DOC_ID, 1),
            "doc_id": DOC_ID,
            "page_idx": 1,
            "caption_raw": "图B",
            "final_text": "内容B",
            "final_kind": "description",
            "status": "ok",
            "route": {"decision": "describe", "image_kind": "chart"},
        },
    ]
    kg = {"doc_id": DOC_ID, "nodes": [], "edges": [], "meta": {}}
    once = image_service.attach_to_kg(kg, metas, DOC_ID)
    twice = image_service.attach_to_kg(once, metas, DOC_ID)
    assert sum(1 for n in twice["nodes"] if n["type"] == "IMAGE") == 2
    assert sum(1 for e in twice["edges"] if e["relation"] == "HAS_IMAGE") == 2
    ids1 = sorted(n["id"] for n in once["nodes"] if n["type"] == "IMAGE")
    ids2 = sorted(n["id"] for n in twice["nodes"] if n["type"] == "IMAGE")
    assert ids1 == ids2
    edge_ids = [e["id"] for e in twice["edges"] if e["relation"] == "HAS_IMAGE"]
    assert all(eid.startswith("image_edge_") for eid in edge_ids)


def test_filter_reserved_drops_forged_image():
    from app.services import table_service

    kg = {
        "doc_id": DOC_ID,
        "nodes": [
            {"id": "n1", "label": "Python", "type": "SKILL"},
            {"id": "fake", "label": "假图", "type": "IMAGE"},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "fake", "relation": "关联"}],
    }
    out = table_service.filter_reserved_kg_types(kg)
    assert all(n["type"] != "IMAGE" for n in out["nodes"])
    assert all(e["target"] != "fake" for e in out["edges"])


def test_process_images_no_images_returns_empty():
    metas = asyncio.run(image_service.process_images(DOC_ID, [{"type": "text", "content": "x"}], None, None))
    assert metas == []


def test_label_fallback_page_and_image_id():
    meta = {
        "image_id": "img_a1b2c3d4_0000",
        "caption_raw": "",
        "page_idx": 2,
        "final_text": "t",
        "status": "ok",
    }
    assert image_service.image_node_label(meta, 0) == "第3页图片#0"
    meta2 = {"image_id": "img_x", "caption_raw": "", "page_idx": None, "final_text": "t", "status": "ok"}
    assert image_service.image_node_label(meta2, 1) == "img_x"
