"""媒体管线集成测试：无 LLM Key 时表格+图片+占位符+KG 仍可完成"""
from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.config import settings
from app.services import image_service, media_store, parsing_service, table_service


DOC_ID = "f00dbabe-1234-5678-9abc-def012345678"


@pytest.fixture(autouse=True)
def _media_tmp(tmp_path, monkeypatch):
    media = tmp_path / "media"
    monkeypatch.setattr(settings, "MEDIA_DIR", str(media))
    monkeypatch.setattr(settings, "TABLE_SUMMARY_ENABLED", True)
    yield


def _png(width=320, height=240) -> bytes:
    img = Image.new("RGB", (width, height), (180, 200, 220))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _zip_with_image() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("images/arch.png", _png())
    return buf.getvalue()


def _content_list() -> list[dict]:
    return [
        {"type": "text", "content": "苏州河雕商业计划书", "page_idx": 0, "text_level": 1},
        {"type": "text", "content": "团队与产品方案见下表与下图。", "page_idx": 0, "text_level": 0},
        {
            "type": "table",
            "content": (
                "<table>"
                "<tr><th>指标</th><th>2024</th><th>2025</th></tr>"
                "<tr><td>营收</td><td>1200万</td><td>1800万</td></tr>"
                "<tr><td>利润</td><td>300万</td><td>450万</td></tr>"
                "</table>"
            ),
            "page_idx": 1,
            "table_caption": "表1 财务数据",
            "table_footnote": "注：内部测算",
        },
        {
            "type": "image",
            "img_path": "images/arch.png",
            "page_idx": 1,
            "img_caption": "图1 系统架构图",
        },
        {"type": "text", "content": "结论：增长稳健。", "page_idx": 2, "text_level": 0},
    ]


def test_media_pipeline_without_llm_keys():
    content_list = _content_list()
    zip_bytes = _zip_with_image()

    # 表格：无 DeepSeek Key → summary failed，但 JSON 落盘
    table_records, _ = asyncio.run(
        table_service.process_tables(DOC_ID, content_list, None, original_name="bp.pdf")
    )
    assert len(table_records) == 1
    assert table_records[0]["summary_status"] == "failed"
    assert table_records[0]["n_rows"] == 2
    assert table_records[0]["n_cols"] == 3
    assert table_records[0]["rows"][0] == ["营收", "1200万", "1800万"]

    # 图片：无 VLM Key → 启发式 + 可选 OCR/降级 caption
    image_metas = asyncio.run(
        image_service.process_images(DOC_ID, content_list, zip_bytes, None)
    )
    assert len(image_metas) == 1
    assert image_metas[0]["status"] in ("ok", "skipped", "failed", "missing_asset")
    assert image_metas[0]["route"]["model"] in ("heuristic", settings.VLM_MODEL)

    # 占位符 markdown
    table_ids = {2: table_records[0]["table_id"]}
    image_ids = {3: image_metas[0]["image_id"]}
    md = parsing_service.content_list_to_markdown(
        content_list, table_ids=table_ids, image_ids=image_ids
    )
    assert f"{{{{TABLE:{table_records[0]['table_id']}}}}}" in md
    assert f"{{{{IMAGE:{image_metas[0]['image_id']}}}}}" in md
    assert "<table>" not in md
    assert "1800万" not in md  # 不再内联完整表

    chunks = parsing_service.content_list_to_chunks(
        content_list,
        split_by="page",
        chunk_size=2000,
        table_ids=table_ids,
        image_ids=image_ids,
    )
    all_refs = [r for c in chunks for r in c.get("media_refs", [])]
    assert table_records[0]["table_id"] in all_refs
    assert image_metas[0]["image_id"] in all_refs

    # KG：DOCUMENT + TABLE + IMAGE + HAS_* 边
    kg = {"doc_id": DOC_ID, "nodes": [], "edges": [], "meta": {}}
    kg = table_service.attach_to_kg(kg, table_records, DOC_ID, original_name="bp.pdf")
    kg = image_service.attach_to_kg(kg, image_metas, DOC_ID, original_name="bp.pdf")
    types = [n["type"] for n in kg["nodes"]]
    assert "DOCUMENT" in types
    assert "TABLE" in types
    assert "IMAGE" in types
    relations = {e["relation"] for e in kg["edges"]}
    assert "HAS_TABLE" in relations
    assert "HAS_IMAGE" in relations

    # 磁盘真相源齐全
    table_path = media_store.table_json_path(DOC_ID, table_records[0]["table_id"])
    meta_path = media_store.image_meta_path(DOC_ID, image_metas[0]["image_id"])
    assert table_path.exists()
    assert meta_path.exists()
    table_json = json.loads(table_path.read_text(encoding="utf-8"))
    assert table_json["schema_version"] == "table-v1"
    meta_json = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta_json["schema_version"] == "image-v1"
    assert "ocr" in meta_json and "describe" in meta_json


def test_rebuild_is_deterministic_for_ids():
    content_list = _content_list()
    r1, _ = asyncio.run(table_service.process_tables(DOC_ID, content_list, None))
    r2, _ = asyncio.run(table_service.process_tables(DOC_ID, content_list, None))
    assert r1[0]["table_id"] == r2[0]["table_id"]

    z = _zip_with_image()
    m1 = asyncio.run(image_service.process_images(DOC_ID, content_list, z, None))
    m2 = asyncio.run(image_service.process_images(DOC_ID, content_list, z, None))
    assert m1[0]["image_id"] == m2[0]["image_id"]
