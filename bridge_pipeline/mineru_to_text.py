"""
Bridge Layer: content_list.json → List[lx.data.Document]
Converts MinerU output to LangExtract input format.

规范依据: bridgepipeline-spec-v1.0.md § 四
"""

import json
from pathlib import Path
from html.parser import HTMLParser
from typing import Optional
import langextract as lx


def html_table_to_md(html_content: str, caption: str = "") -> str:
    """Convert HTML table to Markdown format.

    Args:
        html_content: <table>...</table> HTML string
        caption: Optional table caption/title

    Returns:
        Markdown formatted table string
    """
    class TableParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows = []
            self.current_row = []
            self.in_table = False
            self.in_row = False
            self.in_cell = False
            self.current_cell = []

        def handle_starttag(self, tag, attrs):
            if tag == "table":
                self.in_table = True
            elif tag in ("tr",) and self.in_table:
                self.in_row = True
                self.current_row = []
            elif tag in ("th", "td") and self.in_row:
                self.in_cell = True
                self.current_cell = []

        def handle_endtag(self, tag):
            if tag == "table":
                self.in_table = False
            elif tag == "tr" and self.in_row:
                self.in_row = False
                if self.current_row:
                    self.rows.append(self.current_row)
            elif tag in ("th", "td") and self.in_cell:
                self.in_cell = False
                cell_text = "".join(self.current_cell).strip()
                self.current_row.append(cell_text)

        def handle_data(self, data):
            if self.in_cell:
                self.current_cell.append(data)

    parser = TableParser()
    try:
        parser.feed(html_content)
    except Exception:
        return ""  # Fallback on parse error

    if not parser.rows:
        return ""

    # Build Markdown table
    lines = []
    if caption:
        lines.append(f"{caption}\n")

    for i, row in enumerate(parser.rows):
        lines.append("| " + " | ".join(row) + " |")
        # Insert header separator after first row
        if i == 0:
            lines.append("| " + " | ".join(["---"] * len(row)) + " |")

    return "\n".join(lines) + "\n"


def content_list_to_documents(
    content_list_path: str,
    pdf_stem: str,
    split_by: str = "page",
    include_tables: bool = True,
    skip_types: Optional[set] = None,
) -> list:
    """Convert content_list.json to List[lx.data.Document].

    Args:
        content_list_path: Absolute path to content_list.json
        pdf_stem: PDF file name without extension (e.g., 'my_document')
        split_by: "page" (default) | "section" | "full"
        include_tables: Whether to include table content
        skip_types: Block types to skip (default: image, equation, interline_equation)

    Returns:
        List[lx.data.Document] grouped by page_idx

    规范: §四·4.2 处理逻辑
    """
    if skip_types is None:
        skip_types = {"image", "equation", "interline_equation"}

    content_file = Path(content_list_path)
    if not content_file.exists():
        raise FileNotFoundError(f"content_list.json not found: {content_list_path}")

    blocks = json.loads(content_file.read_text(encoding="utf-8"))
    if not isinstance(blocks, list):
        raise ValueError("content_list.json must be a JSON array")

    # Group blocks by page_idx
    pages: dict[int, list] = {}
    for block in blocks:
        block_type = block.get("type", "")

        # Skip unwanted types
        if block_type in skip_types:
            continue

        # Skip images even if not explicitly listed
        if block_type == "image" and block.get("text", "").strip() == "":
            continue

        page_idx = block.get("page_idx", 0)
        if page_idx not in pages:
            pages[page_idx] = []
        pages[page_idx].append(block)

    # Assemble documents
    documents = []

    if split_by == "page":
        # One document per page
        for page_idx in sorted(pages.keys()):
            text_parts = []
            for block in pages[page_idx]:
                block_type = block.get("type", "")
                content = block.get("text", "")

                if block_type == "text":
                    text_level = block.get("text_level", 0)
                    if text_level > 0:
                        # Title: add # prefix
                        prefix = "#" * text_level
                        text_parts.append(f"{prefix} {content}\n")
                    else:
                        # Normal paragraph
                        text_parts.append(f"{content}\n")

                elif block_type == "table" and include_tables:
                    caption = block.get("table_caption", "")
                    md_table = html_table_to_md(content, caption)
                    if md_table:
                        text_parts.append(md_table)

                elif block_type == "list":
                    text_parts.append(f"{content}\n")

                elif block_type == "code":
                    text_parts.append(f"```\n{content}\n```\n")

            combined_text = "\n".join(text_parts)
            if combined_text.strip():
                doc_id = f"doc_{pdf_stem}_p{page_idx}"
                documents.append(lx.data.Document(document_id=doc_id, text=combined_text))

    elif split_by == "section":
        # One document per H1 section
        current_section = []
        current_section_title = ""

        all_blocks = []
        for page_idx in sorted(pages.keys()):
            all_blocks.extend(pages[page_idx])

        for block_idx, block in enumerate(all_blocks):
            block_type = block.get("type", "")
            content = block.get("text", "")

            if block_type == "text" and block.get("text_level", 0) == 1:
                # Start new section
                if current_section and current_section_title:
                    combined_text = "\n".join(current_section)
                    if combined_text.strip():
                        doc_id = f"doc_{pdf_stem}_sec_{current_section_title[:20]}"
                        documents.append(lx.data.Document(document_id=doc_id, text=combined_text))

                current_section_title = content[:30]  # Use first 30 chars as title
                current_section = [f"# {content}\n"]
            else:
                if block_type == "text":
                    text_level = block.get("text_level", 0)
                    prefix = "#" * text_level if text_level > 0 else ""
                    if prefix:
                        current_section.append(f"{prefix} {content}\n")
                    else:
                        current_section.append(f"{content}\n")

                elif block_type == "table" and include_tables:
                    caption = block.get("table_caption", "")
                    md_table = html_table_to_md(content, caption)
                    if md_table:
                        current_section.append(md_table)

                elif block_type == "list":
                    current_section.append(f"{content}\n")

                elif block_type == "code":
                    current_section.append(f"```\n{content}\n```\n")

        # Add final section
        if current_section and current_section_title:
            combined_text = "\n".join(current_section)
            if combined_text.strip():
                doc_id = f"doc_{pdf_stem}_sec_{current_section_title[:20]}"
                documents.append(lx.data.Document(document_id=doc_id, text=combined_text))

    elif split_by == "full":
        # Single document from entire content
        text_parts = []
        for page_idx in sorted(pages.keys()):
            for block in pages[page_idx]:
                block_type = block.get("type", "")
                content = block.get("text", "")

                if block_type == "text":
                    text_level = block.get("text_level", 0)
                    if text_level > 0:
                        prefix = "#" * text_level
                        text_parts.append(f"{prefix} {content}\n")
                    else:
                        text_parts.append(f"{content}\n")

                elif block_type == "table" and include_tables:
                    caption = block.get("table_caption", "")
                    md_table = html_table_to_md(content, caption)
                    if md_table:
                        text_parts.append(md_table)

                elif block_type == "list":
                    text_parts.append(f"{content}\n")

                elif block_type == "code":
                    text_parts.append(f"```\n{content}\n```\n")

        combined_text = "\n".join(text_parts)
        if combined_text.strip():
            documents.append(lx.data.Document(document_id=f"doc_{pdf_stem}_full", text=combined_text))

    return documents
