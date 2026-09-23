"""SPEC-TABLE：表格结构化 JSON + LLM 总结 + KG 节点"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from app.config import settings
from app.services import llm_client, media_store

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"^\s*\{\{(TABLE|IMAGE):([a-z0-9_]+)\}\}\s*$")


def make_table_id(doc_id: str, seq: int) -> str:
    return f"tbl_{media_store.doc8(doc_id)}_{seq:04d}"


def make_table_node_id(doc_id: str, seq: int) -> str:
    return f"table_{media_store.doc8(doc_id)}_{seq:04d}"


def extract_tables(content_list: list[dict]) -> list[dict]:
    """按 content_list 出现顺序提取 type=table 的 block，并附带确定性 seq。"""
    tables: list[dict] = []
    seq = 0
    for block in content_list or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "table":
            continue
        tables.append({"block": block, "seq": seq})
        seq += 1
    return tables


def _norm_cell(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        parts = [str(v).strip() for v in value if v is not None and str(v).strip()]
        value = " ".join(parts)
    elif value is None:
        value = ""
    text = unescape(str(value))
    text = text.replace("\xa0", " ").replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", text).strip()


class _HtmlTableParser(HTMLParser):
    """解析 HTML table，展开 colspan/rowspan 为规则网格。"""

    def __init__(self) -> None:
        super().__init__()
        self.raw_rows: list[list[dict]] = []
        self._row: list[dict] | None = None
        self._cell: dict | None = None
        self._buf: list[str] = []
        self.in_table = 0
        self.has_th = False
        self.header_like_rows = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: (v or "") for k, v in attrs}
        if tag == "table":
            self.in_table += 1
            return
        if not self.in_table:
            return
        if tag == "tr":
            self._row = []
        elif tag in ("th", "td"):
            if self._row is None:
                self._row = []
            self._cell = {
                "tag": tag,
                "text": "",
                "colspan": max(1, int(attr.get("colspan") or 1)),
                "rowspan": max(1, int(attr.get("rowspan") or 1)),
            }
            self._buf = []
            if tag == "th":
                self.has_th = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self.in_table = max(0, self.in_table - 1)
            return
        if not self.in_table:
            return
        if tag in ("th", "td") and self._cell is not None:
            self._cell["text"] = _norm_cell("".join(self._buf))
            if self._row is None:
                self._row = []
            self._row.append(self._cell)
            self._cell = None
            self._buf = []
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.raw_rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._buf.append(data)


def _expand_spans(raw_rows: list[list[dict]], warnings: list[str] | None = None) -> tuple[list[list[str]], bool]:
    """将带 colspan/rowspan 的单元格展开为矩形网格。"""
    if not raw_rows:
        return [], False
    n_rows = len(raw_rows)
    # 预计算最大列数
    max_cols = 0
    for r_i, row in enumerate(raw_rows):
        c = 0
        for cell in row:
            c += cell["colspan"]
        max_cols = max(max_cols, c)
    if max_cols == 0:
        return [], False

    grid: list[list[str | None]] = [[None] * max_cols for _ in range(n_rows)]
    merge_cells = False
    logical_counts: list[int] = []
    for r_i, row in enumerate(raw_rows):
        c_i = 0
        logical = 0
        for cell in row:
            while c_i < max_cols and grid[r_i][c_i] is not None:
                c_i += 1
            if c_i >= max_cols:
                break
            if cell["colspan"] > 1 or cell["rowspan"] > 1:
                merge_cells = True
            for dr in range(cell["rowspan"]):
                rr = r_i + dr
                if rr >= n_rows:
                    break
                for dc in range(cell["colspan"]):
                    cc = c_i + dc
                    if cc < max_cols and grid[rr][cc] is None:
                        grid[rr][cc] = cell["text"]
            c_i += cell["colspan"]
            logical += cell["colspan"]
        logical_counts.append(logical)
    # 不规则行：补齐/截断到 n_cols，记 warnings（SPEC §5）
    if warnings is not None:
        for r_i, count in enumerate(logical_counts):
            if count < max_cols:
                warnings.append(f"row {r_i}: padded {max_cols - count} empty cell(s)")
            elif count > max_cols:
                warnings.append(f"row {r_i}: truncated {count - max_cols} cell(s)")
    # 裁掉全空尾列
    used_cols = 0
    for c in range(max_cols):
        if any((grid[r][c] or "") != "" for r in range(n_rows)):
            used_cols = c + 1
    out: list[list[str]] = []
    for r in range(n_rows):
        row_vals = [(grid[r][c] or "") for c in range(used_cols)]
        out.append(row_vals)
    return out, merge_cells


def _detect_header_rows(grid: list[list[str]], has_th: bool) -> int:
    """仅当首行使用 <th> 时判定表头；无 <th> 时整表按数据行处理，避免启发式改写语义。"""
    if not grid or not has_th:
        return 0
    return 1


def _pad_rows(rows: list[list[str]], n_cols: int, warnings: list[str] | None = None) -> list[list[str]]:
    padded = []
    for i, row in enumerate(rows):
        r = list(row[:n_cols]) if len(row) > n_cols else list(row)
        if len(row) > n_cols and warnings is not None:
            warnings.append(f"row {i}: truncated {len(row) - n_cols} cell(s)")
        if len(r) < n_cols:
            if warnings is not None:
                warnings.append(f"row {i}: padded {n_cols - len(r)} empty cell(s)")
            r.extend([""] * (n_cols - len(r)))
        padded.append(r)
    return padded


def _md_to_grid(md: str) -> list[list[str]]:
    lines = [ln.rstrip() for ln in md.strip().splitlines() if ln.strip().startswith("|")]
    grid: list[list[str]] = []
    for ln in lines:
        core = ln.strip()
        if core.startswith("|"):
            core = core[1:]
        if core.endswith("|"):
            core = core[:-1]
        cells = [_norm_cell(c) for c in core.split("|")]
        # 分隔行 | --- |
        if cells and all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells if c != "") and any(
            re.fullmatch(r":?-{2,}:?", c or "") for c in cells
        ):
            continue
        # 更稳妥：整行都是 --- 形态
        stripped = [c for c in cells]
        if stripped and all(re.fullmatch(r":?-{3,}:?", c) for c in stripped if c != "") and all(
            c == "" or re.fullmatch(r":?-{3,}:?", c) for c in stripped
        ):
            continue
        if any(c for c in cells):
            grid.append(cells)
    return grid


def _grid_to_md(headers: list[list[str]], rows: list[list[str]], caption: str = "", footnote: str = "") -> str:
    lines: list[str] = []
    if caption:
        lines.append(caption)
    all_rows = headers + rows
    if not all_rows:
        return ""
    n_cols = max(len(r) for r in all_rows)
    for i, row in enumerate(all_rows):
        padded = list(row) + [""] * (n_cols - len(row))
        lines.append("| " + " | ".join(padded) + " |")
        if i == len(headers) - 1 or (i == 0 and not headers and rows):
            # 表头分隔线：在 header 之后；无 header 时在第一行后
            if headers or i == 0:
                lines.append("| " + " | ".join(["---"] * n_cols) + " |")
    if not headers and rows:
        # 已在第一行后插入分隔线
        pass
    if footnote:
        lines.append(footnote)
    return "\n".join(lines) + "\n"


def _empty_record(doc_id: str, table_id: str, block: dict, source_format: str, html_source: str, md_source: str, reason: str | None) -> dict:
    page_idx = block.get("page_idx")
    if not isinstance(page_idx, int):
        page_idx = None
    bbox = block.get("bbox")
    if not isinstance(bbox, list):
        bbox = None
    return {
        "schema_version": "table-v1",
        "table_id": table_id,
        "doc_id": doc_id,
        "page_idx": page_idx,
        "bbox": bbox,
        "caption": _norm_cell(block.get("table_caption") or ""),
        "footnote": _norm_cell(block.get("table_footnote") or ""),
        "source_format": source_format,
        "headers": [],
        "n_header_rows": 0,
        "rows": [],
        "n_rows": 0,
        "n_cols": 0,
        "html_source": html_source if source_format == "html" else "",
        "md_source": md_source if source_format == "markdown" else "",
        "summary": "",
        "summary_status": "failed" if not reason else "skipped",
        "key_entities": [],
        "parse_meta": {
            "parser": "html_table_parser" if source_format == "html" else "md_table_parser",
            "merge_cells": False,
            "warnings": [],
            "skipped_reason": reason,
        },
        "created_at": datetime.utcnow().isoformat() + "Z",
    }


def parse_table(block: dict, doc_id: str, seq: int) -> dict:
    """纯函数：content_list table block → TableRecord（table-v1）。"""
    table_id = make_table_id(doc_id, seq)
    raw = ""
    for key in ("content", "text", "table_body", "table_html"):
        val = block.get(key)
        if isinstance(val, (list, tuple)):
            raw = " ".join(str(v).strip() for v in val if v is not None and str(v).strip())
        elif val is not None:
            raw = str(val).strip()
        if raw:
            break
    caption = _norm_cell(block.get("table_caption") or "")
    footnote = _norm_cell(block.get("table_footnote") or "")
    warnings: list[str] = []
    merge_cells = False
    parser_name = "html_table_parser"
    source_format = "html"
    headers: list[list[str]] = []
    rows: list[list[str]] = []
    html_source = ""
    md_source = ""
    skipped_reason = None

    if not raw:
        return _empty_record(doc_id, table_id, block, "html", "", "", "empty_content")

    if "<table" in raw.lower():
        source_format = "html"
        parser_name = "html_table_parser"
        html_source = raw
        p = _HtmlTableParser()
        try:
            p.feed(raw)
            p.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("HTML table parse failed for %s: %s", table_id, exc)
            # 解析失败 ≠ 装饰性跳过：保留源，仍可建骨架节点
            rec = _empty_record(doc_id, table_id, block, "html", raw, "", None)
            rec["parse_meta"]["parser"] = "failed"
            rec["parse_meta"]["warnings"] = [f"html_parse_error: {exc}"]
            return rec
        grid, merge_cells = _expand_spans(p.raw_rows, warnings)
        if not grid or not any(any(c for c in r) for r in grid):
            return _empty_record(doc_id, table_id, block, "html", raw, "", "empty_cells")
        n_header = _detect_header_rows(grid, p.has_th)
        headers = _pad_rows(grid[:n_header], max(len(r) for r in grid), warnings) if n_header else []
        body = grid[n_header:]
        rows = _pad_rows(body, max(len(r) for r in grid), warnings) if body else []
        md_source = _grid_to_md(headers, rows, caption=caption, footnote=footnote)
    elif raw.lstrip().startswith("|") or "\n|" in raw:
        source_format = "markdown"
        parser_name = "md_table_parser"
        md_source = raw if raw.endswith("\n") else raw + "\n"
        grid = _md_to_grid(raw)
        if not grid or not any(any(c for c in r) for r in grid):
            return _empty_record(doc_id, table_id, block, "markdown", "", raw, "empty_cells")
        # 有分隔行时第一行为表头；否则首行仍作表头（MinerU MD 表惯例）
        headers = [grid[0]]
        rows = grid[1:] if len(grid) > 1 else []
        n_cols = max(len(r) for r in grid)
        headers = _pad_rows(headers, n_cols, warnings)
        rows = _pad_rows(rows, n_cols, warnings) if rows else []
    else:
        # 无法识别：保留原文，failed 但仍建骨架节点
        rec = _empty_record(doc_id, table_id, block, "html", raw, "", None)
        rec["parse_meta"]["parser"] = "failed"
        rec["parse_meta"]["warnings"] = ["unsupported_format"]
        return rec

    n_cols = 0
    if headers:
        n_cols = max(n_cols, max(len(r) for r in headers))
    if rows:
        n_cols = max(n_cols, max(len(r) for r in rows))

    if not rows and not headers:
        skipped_reason = "empty_cells"
    elif len(rows) == 0 and headers and all(not c for c in headers[0]):
        skipped_reason = "empty_cells"

    page_idx = block.get("page_idx") if isinstance(block.get("page_idx"), int) else None
    bbox = block.get("bbox") if isinstance(block.get("bbox"), list) else None

    record = {
        "schema_version": "table-v1",
        "table_id": table_id,
        "doc_id": doc_id,
        "page_idx": page_idx,
        "bbox": bbox,
        "caption": caption,
        "footnote": footnote,
        "source_format": source_format,
        "headers": headers,
        "n_header_rows": len(headers),
        "rows": rows,
        "n_rows": len(rows),
        "n_cols": n_cols,
        "html_source": html_source,
        "md_source": md_source,
        "summary": "",
        "summary_status": "failed",
        "key_entities": [],
        "parse_meta": {
            "parser": parser_name,
            "merge_cells": merge_cells,
            "warnings": warnings,
            "skipped_reason": skipped_reason,
        },
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    return record


def save_table(doc_id: str, record: dict) -> str:
    """落盘 table JSON，返回 table_id。"""
    table_id = record["table_id"]
    path = media_store.table_json_path(doc_id, table_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return table_id


def load_table(doc_id: str, table_id: str) -> dict | None:
    path = media_store.table_json_path(doc_id, table_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def filter_reserved_kg_types(kg: dict) -> dict:
    """丢弃文本抽取伪造的 TABLE/IMAGE 节点及其边（SPEC-TABLE §7.4）。"""
    reserved = {"TABLE", "IMAGE"}
    reserved_ids = {
        n.get("id")
        for n in (kg.get("nodes") or [])
        if str(n.get("type") or "").upper() in reserved
    }
    if not reserved_ids:
        return kg
    kg["nodes"] = [n for n in kg.get("nodes") or [] if n.get("id") not in reserved_ids]
    kg["edges"] = [
        e
        for e in kg.get("edges") or []
        if e.get("source") not in reserved_ids and e.get("target") not in reserved_ids
    ]
    return kg


_REPAIR_SYSTEM = """你是表格修复助手。给定无法自动解析的表格原文，还原为行列结构，严格输出 JSON：
{"headers": [["表头单元格"...]], "rows": [["数据单元格"...]]}
空单元格用空字符串，不要编造数据。"""


async def maybe_repair_table(record: dict, api_key: str | None) -> dict:
    """解析失败时的 LLM 兜底（SHOULD）。成功则写回 headers/rows，parser=llm_repair。"""
    if (record.get("parse_meta") or {}).get("parser") != "failed":
        return record
    if not settings.TABLE_LLM_REPAIR_ENABLED or not api_key:
        return record
    source = record.get("html_source") or record.get("md_source") or ""
    if not source.strip():
        return record
    try:
        content, _usage = await llm_client.chat_complete(
            api_key,
            [
                {"role": "system", "content": _REPAIR_SYSTEM},
                {"role": "user", "content": source[:8000]},
            ],
            temperature=0.0,
            max_tokens=settings.TABLE_SUMMARY_MAX_TOKENS,
            response_format_json=True,
        )
        data = json.loads(content)
        headers = [[_norm_cell(c) for c in row] for row in (data.get("headers") or []) if isinstance(row, list)]
        rows = [[_norm_cell(c) for c in row] for row in (data.get("rows") or []) if isinstance(row, list)]
        if not headers and not rows:
            return record
        n_cols = max((len(r) for r in headers + rows), default=0)
        headers = _pad_rows(headers, n_cols) if headers else []
        rows = _pad_rows(rows, n_cols) if rows else []
        record["headers"] = headers
        record["rows"] = rows
        record["n_header_rows"] = len(headers)
        record["n_rows"] = len(rows)
        record["n_cols"] = n_cols
        record["md_source"] = _grid_to_md(headers, rows, caption=record.get("caption") or "", footnote=record.get("footnote") or "")
        meta = dict(record.get("parse_meta") or {})
        meta["parser"] = "llm_repair"
        meta["skipped_reason"] = None
        meta["warnings"] = list(meta.get("warnings") or []) + ["repaired_by_llm"]
        record["parse_meta"] = meta
        record["summary_status"] = "failed"
    except Exception as exc:  # noqa: BLE001
        logger.warning("table llm repair failed for %s: %s", record.get("table_id"), exc)
    return record


def _should_summarize(record: dict) -> bool:
    if record.get("parse_meta", {}).get("skipped_reason"):
        return False
    if not settings.TABLE_SUMMARY_ENABLED:
        return False
    cells = record.get("n_rows", 0) * max(record.get("n_cols", 0), 1)
    if cells >= settings.TABLE_SUMMARY_MIN_CELLS:
        return True
    return bool((record.get("caption") or "").strip())


def _sample_md_for_prompt(record: dict) -> str:
    headers = record.get("headers") or []
    rows = record.get("rows") or []
    max_rows = settings.TABLE_MAX_ROWS_FOR_FULL_PROMPT
    sampled = False
    if len(rows) > max_rows:
        rows = rows[:30] + rows[-10:]
        sampled = True
    n_cols = record.get("n_cols") or (max((len(r) for r in headers + rows), default=0))
    lines = []
    if headers:
        for h in headers:
            padded = list(h) + [""] * (n_cols - len(h))
            lines.append("| " + " | ".join(padded) + " |")
        lines.append("| " + " | ".join(["---"] * n_cols) + " |")
    for r in rows:
        padded = list(r) + [""] * (n_cols - len(r))
        lines.append("| " + " | ".join(padded) + " |")
    md = "\n".join(lines)
    if sampled:
        md = "（以下为部分行）\n" + md
    return md


_SUMMARY_SYSTEM = """你是专业的表格分析助手。请阅读给定表格，输出严格的 JSON，不要输出多余文字。
JSON 格式：
{
  "summary": "2-4句中文：表主题、关键对比/趋势、异常值。不得改写表格中的关键数值。",
  "key_entities": ["关键词1", "关键词2"],
  "answer_hints": ["适合回答的问题类型"]
}"""


async def summarize(record: dict, api_key: str | None) -> dict:
    """调用 LLM 生成表格总结，失败时降级且不抛穿。原地更新并返回 record。"""
    if record.get("parse_meta", {}).get("skipped_reason"):
        record["summary"] = ""
        record["summary_status"] = "skipped"
        record["key_entities"] = []
        return record
    if not _should_summarize(record):
        record["summary"] = ""
        record["summary_status"] = "skipped"
        record["key_entities"] = []
        return record
    if not api_key or not llm_client.llm_available(api_key):
        record["summary"] = ""
        record["summary_status"] = "failed"
        record["key_entities"] = []
        return record

    md = record.get("md_source") or _sample_md_for_prompt(record)
    if len(md) > 6000:
        md = md[:6000]
    parts = []
    if record.get("caption"):
        parts.append(f"标题：{record['caption']}")
    parts.append(md)
    if record.get("footnote"):
        parts.append(f"脚注：{record['footnote']}")
    user_prompt = "\n\n".join(parts)

    try:
        content, _usage = await llm_client.chat_complete(
            api_key,
            [
                {"role": "system", "content": _SUMMARY_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=settings.TABLE_SUMMARY_MAX_TOKENS,
            response_format_json=True,
        )
        data = json.loads(content)
        summary = str(data.get("summary") or "").strip()
        key_entities = [str(x) for x in (data.get("key_entities") or []) if str(x).strip()][:12]
        if not summary:
            raise ValueError("empty summary")
        record["summary"] = summary
        record["key_entities"] = key_entities
        record["summary_status"] = "ok"
        hints = [str(x) for x in (data.get("answer_hints") or []) if str(x).strip()]
        if hints:
            record.setdefault("parse_meta", {})["answer_hints"] = hints
    except Exception as exc:  # noqa: BLE001
        logger.warning("table summarize failed for %s: %s", record.get("table_id"), exc)
        record["summary"] = ""
        record["summary_status"] = "failed"
        record["key_entities"] = []
    return record


def _skeleton_label(record: dict) -> str:
    caption = (record.get("caption") or "").strip()
    if caption:
        return caption[:80]
    headers = record.get("headers") or []
    if headers and headers[0]:
        joined = " | ".join(c for c in headers[0] if c)[:30]
        if joined:
            return joined
    return record.get("table_id") or "未命名表格"


def _match_entities(record: dict, existing_labels: set[str]) -> list[str]:
    candidates: list[str] = []
    for e in record.get("key_entities") or []:
        candidates.append(str(e).strip())
    summary = record.get("summary") or ""
    for label in existing_labels:
        if label and label in summary:
            candidates.append(label)
    # 表头中与既有实体精确匹配的项
    for row in (record.get("headers") or []) + (record.get("rows") or [])[:5]:
        for cell in row:
            cell = (cell or "").strip()
            if cell and cell in existing_labels:
                candidates.append(cell)
    seen = set()
    out = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def attach_to_kg(
    kg: dict,
    records: list[dict],
    doc_id: str,
    original_name: str = "",
) -> dict:
    """写入 DOCUMENT + TABLE 节点与 HAS_TABLE / MENTIONS 边。"""
    kg = media_store.ensure_document_node(kg, doc_id, original_name)
    doc_node_id = media_store.find_document_node_id(kg, doc_id) or f"doc_{media_store.doc8(doc_id)}"

    existing_ids = {n.get("id") for n in kg.get("nodes") or []}
    existing_labels = {
        str(n.get("label") or "").strip()
        for n in kg.get("nodes") or []
        if n.get("type") not in ("DOCUMENT", "TABLE", "IMAGE") and n.get("label")
    }
    label_to_id = {
        str(n.get("label") or "").strip(): n.get("id")
        for n in kg.get("nodes") or []
        if n.get("type") not in ("DOCUMENT", "TABLE", "IMAGE") and n.get("label")
    }
    edges = kg.setdefault("edges", [])
    edge_keys = {(e.get("source"), e.get("target"), e.get("relation")) for e in edges}

    for record in records:
        if record.get("parse_meta", {}).get("skipped_reason"):
            continue
        seq = int(record["table_id"].rsplit("_", 1)[-1])
        node_id = make_table_node_id(doc_id, seq)
        # 重建时覆盖同 id 节点
        if node_id in existing_ids:
            kg["nodes"] = [n for n in kg["nodes"] if n.get("id") != node_id]
            edges[:] = [e for e in edges if e.get("source") != node_id]
            existing_ids.discard(node_id)

        label = _skeleton_label(record)
        node = {
            "id": node_id,
            "label": label,
            "type": "TABLE",
            "attributes": {
                "media_id": record["table_id"],
                "page_idx": record.get("page_idx"),
                "n_rows": record.get("n_rows", 0),
                "n_cols": record.get("n_cols", 0),
                "caption": record.get("caption") or "",
                "summary": record.get("summary") or "",
                "summary_status": record.get("summary_status") or "failed",
                "source_ref": f"{{{{TABLE:{record['table_id']}}}}}",
            },
        }
        kg["nodes"].append(node)
        existing_ids.add(node_id)

        has_key = (doc_node_id, node_id, "HAS_TABLE")
        if has_key not in edge_keys:
            edges.append(media_store.new_edge(doc_node_id, node_id, "HAS_TABLE"))
            edge_keys.add(has_key)

        for ent_label in _match_entities(record, existing_labels):
            target = label_to_id.get(ent_label)
            if not target:
                continue
            m_key = (node_id, target, "MENTIONS")
            if m_key not in edge_keys:
                edges.append(media_store.new_edge(node_id, target, "MENTIONS"))
                edge_keys.add(m_key)

    kg.setdefault("meta", {})
    kg["meta"]["total_nodes"] = len(kg["nodes"])
    kg["meta"]["total_edges"] = len(kg["edges"])
    return kg


async def process_tables(
    doc_id: str,
    content_list: list[dict],
    api_key: str | None,
    original_name: str = "",
) -> tuple[list[dict], dict | None]:
    """主入口：提取 → 解析 →（可选）LLM 修复 → 落盘 → 总结。返回 (records, None)。

    不直接写 KG 文件；由 index 流水线在拿到文本 KG 后调用 attach_to_kg。
    """
    extracted = extract_tables(content_list)
    records: list[dict] = []
    for item in extracted:
        block = item["block"]
        seq = item["seq"]
        record = parse_table(block, doc_id, seq)
        if (record.get("parse_meta") or {}).get("parser") == "failed":
            record = await maybe_repair_table(record, api_key)
        if record.get("parse_meta", {}).get("skipped_reason"):
            record["summary_status"] = "skipped"
            record["summary"] = ""
            record["key_entities"] = []
        else:
            record = await summarize(record, api_key)
        save_table(doc_id, record)
        records.append(record)
    if records:
        media_store.write_manifest(doc_id, [r["table_id"] for r in records], [])
    return records, None
