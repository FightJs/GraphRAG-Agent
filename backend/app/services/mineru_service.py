"""MinerU Cloud API 客户端 — 批量上传 PDF 并拉取结构化 content_list.json"""
from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path

import httpx

from app.config import settings


class MinerUError(Exception):
    pass


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _pick_upload_url(file_info) -> str:
    if isinstance(file_info, str):
        return file_info
    if isinstance(file_info, dict):
        return (
            file_info.get("url")
            or file_info.get("upload_url")
            or file_info.get("presigned_url")
            or ""
        )
    return ""


async def _download_bytes(client: httpx.AsyncClient, url: str, retries: int = 4) -> bytes:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = await client.get(url, timeout=60.0)
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPError as exc:
            last_err = exc
            if attempt < retries:
                await asyncio.sleep(2 ** (attempt - 1))
    raise MinerUError(f"下载失败: {url[:80]}... — {last_err}")


async def extract_pdf(api_key: str, file_path: str, filename: str | None = None) -> dict:
    """解析本地 PDF，返回 {"content_list": list, "markdown": str|None, "page_count": int, "zip_bytes": bytes|None}。

    流程：POST /file-urls/batch → PUT 预签名 URL → 轮询 /extract-results/batch/{id}
    → 下载 content_list.json；有图时尽量一并下载 zip 以便落盘 images/**。
    """
    pdf_path = Path(file_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")
    name = filename or pdf_path.name
    payload = {
        "enable_table": settings.MINERU_ENABLE_TABLE,
        "enable_formula": settings.MINERU_ENABLE_FORMULA,
        "language": settings.MINERU_LANGUAGE,
        "files": [{"name": name, "is_ocr": settings.MINERU_ENABLE_OCR}],
    }
    submit_headers = _auth(api_key)
    submit_headers["Content-Type"] = "application/json"

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            batch_resp = await client.post(
                f"{settings.MINERU_BASE_URL}/file-urls/batch",
                headers=submit_headers,
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise MinerUError(f"MinerU 提交失败: {exc}") from exc
        if batch_resp.status_code >= 400:
            raise MinerUError(f"file-urls/batch HTTP {batch_resp.status_code}: {batch_resp.text[:400]}")
        body = batch_resp.json()
        if body.get("code") != 0:
            raise MinerUError(f"file-urls/batch error: {body}")

        data = body.get("data") or {}
        batch_id = data.get("batch_id")
        raw_list = data.get("file_urls") or []
        if not batch_id or not raw_list:
            raise MinerUError(f"batch 响应缺少 batch_id/file_urls: {body}")

        upload_url = _pick_upload_url(raw_list[0])
        if not upload_url:
            raise MinerUError(f"无法从 file_urls 取得上传地址: {raw_list[0]}")

        file_bytes = pdf_path.read_bytes()
        try:
            # 预签名 URL 内嵌签名，不能附带自定义 header
            put_resp = await client.put(upload_url, content=file_bytes)
        except httpx.HTTPError as exc:
            raise MinerUError(f"OSS 上传失败: {exc}") from exc
        if put_resp.status_code >= 400:
            raise MinerUError(f"OSS PUT HTTP {put_resp.status_code}: {put_resp.text[:300]}")

        result = await _poll_batch(client, api_key, batch_id)
        return await _fetch_outputs(client, result)


async def _poll_batch(client: httpx.AsyncClient, api_key: str, batch_id: str) -> dict:
    url = f"{settings.MINERU_BASE_URL}/extract-results/batch/{batch_id}"
    deadline = asyncio.get_event_loop().time() + settings.MINERU_POLL_TIMEOUT
    while asyncio.get_event_loop().time() < deadline:
        try:
            resp = await client.get(url, headers=_auth(api_key))
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise MinerUError(f"轮询失败: {exc}") from exc
        body = resp.json()
        if body.get("code") != 0:
            raise MinerUError(f"batch poll error: {body}")
        items = (body.get("data") or {}).get("extract_result") or []
        if not items:
            await asyncio.sleep(settings.MINERU_POLL_INTERVAL)
            continue
        item = items[0]
        state = item.get("state")
        if state == "done":
            result = item.get("result") or {}
            if result.get("content_list_url") or result.get("full_zip_url") or result.get("zip_url"):
                return result
            if item.get("full_zip_url"):
                return item
            raise MinerUError(f"完成结果缺少下载链接: {item}")
        if state == "failed":
            raise MinerUError(f"MinerU 解析失败: {item.get('err_msg') or 'unknown'}")
        await asyncio.sleep(settings.MINERU_POLL_INTERVAL)
    raise MinerUError(f"MinerU 任务超时: batch_id={batch_id}")


def _content_list_has_images(content_list: list) -> bool:
    for b in content_list:
        if not isinstance(b, dict) or b.get("type") != "image":
            continue
        img_path = b.get("img_path")
        if isinstance(img_path, (list, tuple)):
            if any(str(x).strip() for x in img_path if x is not None):
                return True
        elif img_path is not None and str(img_path).strip():
            return True
    return False


async def _fetch_outputs(client: httpx.AsyncClient, result: dict) -> dict:
    content_list: list = []
    markdown: str | None = None
    zip_bytes: bytes | None = None

    content_list_url = result.get("content_list_url")
    if content_list_url:
        raw = await _download_bytes(client, content_list_url)
        content_list = json.loads(raw.decode("utf-8"))

    markdown_url = result.get("markdown_url")
    if markdown_url:
        raw = await _download_bytes(client, markdown_url)
        markdown = raw.decode("utf-8", errors="ignore")

    zip_url = result.get("full_zip_url") or result.get("zip_url")

    if not content_list:
        if not zip_url:
            raise MinerUError(f"MinerU 结果中没有 content_list/zip: {result}")
        zip_bytes = await _download_bytes(client, zip_url)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            member = next((n for n in names if n.endswith("content_list.json")), None)
            if not member:
                raise MinerUError(f"zip 中未找到 content_list.json: {names}")
            content_list = json.loads(zf.read(member).decode("utf-8"))
            md_member = next((n for n in names if n.endswith("output.md")), None)
            if md_member:
                markdown = zf.read(md_member).decode("utf-8", errors="ignore")

    if not isinstance(content_list, list):
        raise MinerUError("content_list.json 顶层必须是数组")

    # 有图且尚未从 zip 解出时，额外下载 zip 供图片落盘（SPEC-IMAGE 前置硬依赖）
    if zip_bytes is None and zip_url and _content_list_has_images(content_list):
        try:
            zip_bytes = await _download_bytes(client, zip_url)
        except MinerUError:
            zip_bytes = None

    page_idxes = {b.get("page_idx") for b in content_list if isinstance(b, dict)}
    page_count = (max((p for p in page_idxes if isinstance(p, int)), default=-1) + 1) or len(content_list)

    return {
        "content_list": content_list,
        "markdown": markdown,
        "page_count": page_count,
        "zip_bytes": zip_bytes,
    }
