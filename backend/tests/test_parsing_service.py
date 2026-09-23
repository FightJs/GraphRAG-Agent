"""MinerU content_list 结构化解析 / 分块单元测试"""
from app.services import parsing_service


SAMPLE_BLOCKS = [
    {
        "type": "text",
        "content": "# 苏州河雕商业计划书",
        "page_idx": 0,
        "text_level": 1,
    },
    {
        "type": "text",
        "content": "公司专注AI驱动的工业视觉检测。",
        "page_idx": 0,
        "text_level": 0,
    },
    {
        "type": "text",
        "content": "## 市场分析",
        "page_idx": 0,
        "text_level": 2,
    },
    {
        "type": "text",
        "content": "团队与融资细节见后续章节。",
        "page_idx": 1,
        "text_level": 0,
    },
    {
        "type": "table",
        "content": "<table><tr><th>指标</th><th>2024</th></tr><tr><td>营收</td><td>1200万</td></tr></table>",
        "page_idx": 2,
        "table_caption": "表1 财务数据",
    },
    {
        "type": "image",
        "content": "",
        "page_idx": 2,
        "img_path": "images/a.png",
    },
    {
        "type": "text",
        # 兼容少数实现把正文放在 text 字段
        "text": "text 字段兼容内容",
        "page_idx": 3,
        "text_level": 0,
    },
]


def test_content_list_to_markdown_skips_images_and_renders_table():
    md = parsing_service.content_list_to_markdown(SAMPLE_BLOCKS)
    assert "# 苏州河雕商业计划书" in md
    assert "## 市场分析" in md
    assert "表1 财务数据" in md
    assert "| 指标 | 2024 |" in md
    assert "images/a.png" not in md


def test_content_list_to_chunks_by_page():
    chunks = parsing_service.content_list_to_chunks(SAMPLE_BLOCKS, split_by="page", chunk_size=2000)
    pages = {c["page_idx"] for c in chunks}
    assert pages == {0, 1, 2, 3}
    assert all("text" in c and "chunk_index" in c for c in chunks)
    page0 = next(c for c in chunks if c["page_idx"] == 0)
    assert "苏州河雕" in page0["text"]
    page3 = next(c for c in chunks if c["page_idx"] == 3)
    assert "text 字段兼容内容" in page3["text"]


def test_content_list_to_chunks_by_section():
    chunks = parsing_service.content_list_to_chunks(SAMPLE_BLOCKS, split_by="section", chunk_size=2000)
    assert chunks
    titles = [c["section"] for c in chunks if c.get("section")]
    assert any("苏州河雕" in t for t in titles)


def test_content_list_to_chunks_full_and_overflow_split():
    long_text = "字" * 50
    blocks = [
        {"type": "text", "content": long_text, "page_idx": 0, "text_level": 0},
    ]
    chunks = parsing_service.content_list_to_chunks(blocks, split_by="page", chunk_size=20, overlap=5)
    assert len(chunks) > 1
    assert all(c["page_idx"] == 0 for c in chunks)
    full = parsing_service.content_list_to_chunks(blocks, split_by="full", chunk_size=20, overlap=5)
    assert all(c["page_idx"] is None for c in full)


def test_normalize_chunks_legacy_and_new():
    legacy = ["hello world", "second"]
    normalized = parsing_service.normalize_chunks(legacy)
    assert normalized[0]["text"] == "hello world"
    assert normalized[0]["page_idx"] is None
    new = [{"text": "a", "page_idx": 2, "section": "s", "chunk_index": 0}]
    assert parsing_service.normalize_chunks(new)[0]["page_idx"] == 2
    assert parsing_service.chunks_as_texts(new) == ["a"]
    assert parsing_service.chunks_as_texts(legacy) == ["hello world", "second"]


def test_plain_text_to_chunks():
    chunks = parsing_service.plain_text_to_chunks("abc" * 10, chunk_size=10, overlap=2)
    assert chunks
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["page_idx"] is None


def test_as_text_coerces_list_and_none():
    assert parsing_service.as_text(None) == ""
    assert parsing_service.as_text("  hi  ") == "hi"
    assert parsing_service.as_text(["表1 ", "财务数据"]) == "表1 财务数据"
    assert parsing_service.as_text((None, "注：x", "")) == "注：x"


def test_content_list_list_caption_and_footnote_do_not_crash():
    blocks = [
        {
            "type": "table",
            "table_body": "<table><tr><th>指标</th><th>值</th></tr><tr><td>营收</td><td>1</td></tr></table>",
            "page_idx": 0,
            "table_caption": ["表1 ", "财务数据"],
            "table_footnote": ["注：内部测算"],
        },
        {
            "type": "image",
            "img_path": "images/a.png",
            "img_caption": ["图1", "架构图"],
            "image_caption": ["图1 架构图"],
            "page_idx": 0,
        },
        {
            "type": "text",
            "content": ["第一行", "第二行"],
            "page_idx": 1,
            "text_level": 0,
        },
    ]
    md = parsing_service.content_list_to_markdown(
        blocks, table_ids={0: "tbl_x_0000"}, image_ids={1: "img_x_0000"}
    )
    assert "表1 财务数据" in md
    assert "{{TABLE:tbl_x_0000}}" in md
    assert "注：内部测算" in md
    assert "图1 架构图" in md
    assert "{{IMAGE:img_x_0000}}" in md
    assert "第一行 第二行" in md

    chunks = parsing_service.content_list_to_chunks(
        blocks,
        split_by="page",
        chunk_size=2000,
        table_ids={0: "tbl_x_0000"},
        image_ids={1: "img_x_0000"},
    )
    assert chunks
    assert any("表1 财务数据" in c["text"] for c in chunks)
    assert any("第一行 第二行" in c["text"] for c in chunks)
