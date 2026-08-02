"""文档解析服务 — 将上传的原始文件提取为纯文本，供 KG 抽取和问答使用"""
from pathlib import Path

from pypdf import PdfReader
from docx import Document as DocxDocument
from openpyxl import load_workbook
from pptx import Presentation
from bs4 import BeautifulSoup


def extract_text(file_path: str, file_format: str) -> tuple[str, int]:
    """返回 (纯文本, 页数/分片数估计)"""
    fmt = file_format.lower()
    if fmt == "pdf":
        return _extract_pdf(file_path)
    if fmt == "docx":
        return _extract_docx(file_path)
    if fmt == "xlsx":
        return _extract_xlsx(file_path)
    if fmt == "pptx":
        return _extract_pptx(file_path)
    if fmt == "html":
        return _extract_html(file_path)
    if fmt in ("txt", "md", "csv"):
        text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        return text, max(1, text.count("\n") // 40 + 1)
    raise ValueError(f"5001:不支持解析的文件格式 {fmt}")


def _extract_pdf(file_path: str) -> tuple[str, int]:
    reader = PdfReader(file_path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages), len(reader.pages)


def _extract_docx(file_path: str) -> tuple[str, int]:
    doc = DocxDocument(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            paragraphs.append(" | ".join(cell.text for cell in row.cells))
    text = "\n".join(paragraphs)
    return text, max(1, len(paragraphs) // 30 + 1)


def _extract_xlsx(file_path: str) -> tuple[str, int]:
    wb = load_workbook(file_path, data_only=True, read_only=True)
    lines = []
    for sheet in wb.worksheets:
        lines.append(f"# 表: {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines), len(wb.worksheets)


def _extract_pptx(file_path: str) -> tuple[str, int]:
    prs = Presentation(file_path)
    lines = []
    for i, slide in enumerate(prs.slides, 1):
        lines.append(f"# 幻灯片 {i}")
        for shape in slide.shapes:
            if shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    lines.append(text)
    return "\n".join(lines), len(prs.slides)


def _extract_html(file_path: str) -> tuple[str, int]:
    html = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    return text, max(1, text.count("\n") // 40 + 1)


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> list[str]:
    """按字符数滑动窗口分块，中文场景下按字符切分足够实用"""
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        chunks.append(text[start:end])
        if end == n:
            break
        start = end - overlap
    return chunks
