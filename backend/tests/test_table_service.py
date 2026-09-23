"""SPEC-TABLE 单元测试：解析、落盘、KG 节点、类型隔离"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.config import settings
from app.services import kg_extraction, parsing_service, table_service


DOC_ID = "a1b2c3d4-1111-2222-3333-444455556666"


@pytest.fixture(autouse=True)
def _media_tmp(tmp_path, monkeypatch):
    media = tmp_path / "media"
    monkeypatch.setattr(settings, "MEDIA_DIR", str(media))
    yield


HTML_TABLE = (
    "<table>"
    "<tr><th>指标</th><th>A组</th><th>B组</th></tr>"
    "<tr><td>准确率</td><td>91.2%</td><td>88.5%</td></tr>"
    "<tr><td>召回率</td><td>87.0%</td><td>90.1%</td></tr>"
    "</table>"
)

HTML_COLSPAN = (
    "<table>"
    "<tr><th colspan='2'>合并表头</th><th>值</th></tr>"
    "<tr><td rowspan='2'>跨行</td><td>a</td><td>1</td></tr>"
    "<tr><td>b</td><td>2</td></tr>"
    "</table>"
)

MD_TABLE = "| 指标 | 2024 |\n| --- | --- |\n| 营收 | 1200万 |\n| 利润 | 300万 |"


def _table_block(content: str, caption: str = "表1 实验结果", page_idx: int = 1) -> dict:
    return {
        "type": "table",
        "content": content,
        "page_idx": page_idx,
        "table_caption": caption,
        "table_footnote": "注：实测数据",
        "bbox": [10, 20, 300, 400],
    }


def test_extract_tables_deterministic_seq():
    blocks = [
        {"type": "text", "content": "前言", "page_idx": 0},
        _table_block(HTML_TABLE),
        {"type": "image", "img_path": "images/a.png", "page_idx": 1},
        _table_block(MD_TABLE, caption="表2 财务"),
    ]
    extracted = table_service.extract_tables(blocks)
    assert [e["seq"] for e in extracted] == [0, 1]
    assert table_service.make_table_id(DOC_ID, 0) == f"tbl_{DOC_ID[:8]}_0000"
    assert table_service.make_table_id(DOC_ID, 1) == f"tbl_{DOC_ID[:8]}_0001"


def test_parse_html_table_schema():
    record = table_service.parse_table(_table_block(HTML_TABLE), DOC_ID, 0)
    assert record["schema_version"] == "table-v1"
    assert record["table_id"] == f"tbl_{DOC_ID[:8]}_0000"
    assert record["n_header_rows"] == 1
    assert record["headers"] == [["指标", "A组", "B组"]]
    assert record["n_rows"] == 2
    assert record["n_cols"] == 3
    assert record["rows"][0] == ["准确率", "91.2%", "88.5%"]
    assert record["caption"] == "表1 实验结果"
    assert record["footnote"] == "注：实测数据"
    assert record["page_idx"] == 1
    assert record["parse_meta"]["merge_cells"] is False
    assert record["html_source"]


def test_parse_table_accepts_list_fields_and_table_body():
    block = {
        "type": "table",
        "table_body": HTML_TABLE,
        "page_idx": 0,
        "table_caption": ["表1", "实验结果"],
        "table_footnote": ["注：", "实测数据"],
    }
    record = table_service.parse_table(block, DOC_ID, 0)
    assert record["caption"] == "表1 实验结果"
    assert record["footnote"] == "注： 实测数据"
    assert record["rows"][0] == ["准确率", "91.2%", "88.5%"]
    assert "| 指标 | A组 | B组 |" in record["md_source"]
    # 不得改写数值
    assert "91.2%" in record["md_source"]


def test_parse_colspan_rowspan_expand():
    record = table_service.parse_table(_table_block(HTML_COLSPAN, caption="合并单元格"), DOC_ID, 0)
    assert record["parse_meta"]["merge_cells"] is True
    # 表头 colspan=2 展开
    assert record["headers"][0] == ["合并表头", "合并表头", "值"]
    # rowspan 展开
    assert record["rows"][0][0] == "跨行"
    assert record["rows"][1][0] == "跨行"
    assert record["rows"][0][1] == "a"
    assert record["rows"][1][1] == "b"


def test_parse_markdown_table():
    record = table_service.parse_table(_table_block(MD_TABLE, caption="表2 财务"), DOC_ID, 0)
    assert record["source_format"] == "markdown"
    assert record["headers"] == [["指标", "2024"]]
    assert record["n_rows"] == 2
    assert record["rows"][0] == ["营收", "1200万"]


def test_parse_empty_table_skipped():
    record = table_service.parse_table(_table_block("<table></table>", caption="空表"), DOC_ID, 0)
    assert record["parse_meta"]["skipped_reason"] in ("empty_cells", "empty_content", "html_parse_error")
    assert record["rows"] == []


def test_save_table_and_idempotent(tmp_path):
    record = table_service.parse_table(_table_block(HTML_TABLE), DOC_ID, 0)
    tid = table_service.save_table(DOC_ID, record)
    path = Path(settings.MEDIA_DIR) / DOC_ID / "tables" / f"{tid}.json"
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["table_id"] == tid
    # 重建覆盖写
    record2 = dict(record)
    record2["summary"] = "更新后的摘要"
    table_service.save_table(DOC_ID, record2)
    loaded2 = json.loads(path.read_text(encoding="utf-8"))
    assert loaded2["summary"] == "更新后的摘要"
    assert loaded2["table_id"] == tid


def test_summarize_without_llm_key():
    record = table_service.parse_table(_table_block(HTML_TABLE), DOC_ID, 0)
    result = asyncio.run(table_service.summarize(record, None))
    assert result["summary_status"] == "failed"
    assert result["summary"] == ""
    # JSON 仍可保留
    tid = table_service.save_table(DOC_ID, result)
    assert tid


def test_summarize_skips_small_table():
    tiny = "<table><tr><td>x</td></tr></table>"
    record = table_service.parse_table(_table_block(tiny, caption=""), DOC_ID, 0)
    result = asyncio.run(table_service.summarize(record, "fake-key-not-used"))
    assert result["summary_status"] in ("skipped", "failed")


def test_attach_to_kg_creates_document_and_table_nodes():
    record = table_service.parse_table(_table_block(HTML_TABLE), DOC_ID, 0)
    record["summary_status"] = "failed"
    record["summary"] = ""
    kg = {
        "doc_id": DOC_ID,
        "nodes": [
            {
                "id": "concept_1_x",
                "label": "A组",
                "type": "CONCEPT",
                "attributes": {},
            }
        ],
        "edges": [],
        "meta": {},
    }
    kg = table_service.attach_to_kg(kg, [record], DOC_ID, original_name="demo.pdf")
    types = {n["type"] for n in kg["nodes"]}
    assert "DOCUMENT" in types
    assert "TABLE" in types
    table_nodes = [n for n in kg["nodes"] if n["type"] == "TABLE"]
    assert len(table_nodes) == 1
    tn = table_nodes[0]
    assert tn["attributes"]["media_id"] == record["table_id"]
    assert tn["attributes"]["source_ref"] == f"{{{{TABLE:{record['table_id']}}}}}"
    relations = {(e["source"], e["relation"], e["target"]) for e in kg["edges"]}
    doc_id_node = next(n["id"] for n in kg["nodes"] if n["type"] == "DOCUMENT")
    assert (doc_id_node, "HAS_TABLE", tn["id"]) in relations


def test_attach_to_kg_skips_skipped_tables():
    record = table_service.parse_table(_table_block("<table></table>"), DOC_ID, 0)
    kg = {"doc_id": DOC_ID, "nodes": [], "edges": [], "meta": {}}
    kg = table_service.attach_to_kg(kg, [record], DOC_ID, original_name="demo.pdf")
    assert not any(n["type"] == "TABLE" for n in kg["nodes"])


def test_kg_extraction_drops_reserved_types():
    nodes = [
        {"local_id": "n1", "label": "假表格", "type": "TABLE"},
        {"local_id": "n2", "label": "假图片", "type": "IMAGE"},
        {"local_id": "n3", "label": "真实概念", "type": "CONCEPT"},
    ]
    kept = kg_extraction.sanitize_exclusive_types(nodes)
    assert [n["label"] for n in kept] == ["真实概念"]


def test_placeholder_markdown_and_media_refs():
    blocks = [
        {"type": "text", "content": "实验结果如下", "page_idx": 0, "text_level": 0},
        _table_block(HTML_TABLE),
        {
            "type": "image",
            "img_path": "images/a.png",
            "page_idx": 0,
            "img_caption": "图1 架构",
        },
    ]
    table_ids = {1: "tbl_a1b2c3d4_0000"}
    image_ids = {2: "img_a1b2c3d4_0000"}
    md = parsing_service.content_list_to_markdown(blocks, table_ids=table_ids, image_ids=image_ids)
    assert "{{TABLE:tbl_a1b2c3d4_0000}}" in md
    assert "{{IMAGE:img_a1b2c3d4_0000}}" in md
    assert "<table>" not in md
    assert "表1 实验结果" in md

    chunks = parsing_service.content_list_to_chunks(
        blocks, split_by="page", chunk_size=2000, table_ids=table_ids, image_ids=image_ids
    )
    assert any("tbl_a1b2c3d4_0000" in c.get("media_refs", []) for c in chunks)
    assert any("img_a1b2c3d4_0000" in c.get("media_refs", []) for c in chunks)


def test_chunker_does_not_split_placeholder():
    # 构造刚好会切在占位符中间的文本
    ph = "{{TABLE:tbl_a1b2c3d4_0001}}"
    text = "前缀" * 30 + ph + "后缀" * 30
    chunks = parsing_service.chunk_text(text, chunk_size=50, overlap=10)
    joined = "".join(chunks)
    # 占位符必须完整出现在某个 chunk 中
    assert any(ph in c for c in chunks)
    assert len(joined) >= len(text) - 20


def test_normalize_chunks_defaults_media_refs():
    legacy = ["hello"]
    norm = parsing_service.normalize_chunks(legacy)
    assert norm[0]["media_refs"] == []
    with_refs = [{"text": "x {{TABLE:tbl_x_0000}}", "page_idx": 1}]
    norm2 = parsing_service.normalize_chunks(with_refs)
    assert norm2[0]["media_refs"] == ["tbl_x_0000"]
