"""
Flask Backend for BridgePipeline Visualization
Handles PDF upload, MinerU polling, LangExtract extraction, and SSE streaming

规范依据: bridgepipeline-spec-v1.0.md § 一、六
"""

import os
import sys
import json
import time
import uuid
import requests
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, Response
import langextract as lx
from langextract.providers.openai import OpenAILanguageModel

from mineru_to_text import content_list_to_documents
from graph_builder import build_knowledge_graph, save_knowledge_graph

load_dotenv()

app = Flask(__name__, static_folder="static", static_url_path="/static")

# Global job state (in-memory, demo-level)
jobs: dict = {}

# MinerU configuration
MINERU_API_TOKEN = os.getenv("MINERU_API_TOKEN")
MINERU_BASE_URL = os.getenv("MINERU_BASE_URL", "https://mineru.net/api/v4")
MINERU_LANGUAGE = os.getenv("MINERU_LANGUAGE", "ch")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "3"))
POLL_TIMEOUT = int(os.getenv("POLL_TIMEOUT", "300"))

# LangExtract configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Upload directory
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


def submit_mineru_task(pdf_path: str, progress_callback=None) -> dict:
    """Submit PDF to MinerU Cloud API via batch upload flow.

    正确的 v4 流程（官方文档确认）：
    1. POST /file-urls/batch  —— 请求体带上提取参数（is_ocr/enable_table/
       language 等）→ 返回 batch_id + 预签名 PUT URL
    2. PUT 文件到预签名 URL（不加任何自定义 header）
    3. 上传完成后 MinerU 自动扫描并提交提取任务，无需第二次调用
    4. 用返回的 batch_id 轮询 /extract-results/batch/{batch_id}

    Returns {"mode": "batch", "id": "<batch_id>"}
    """
    if not MINERU_API_TOKEN:
        raise RuntimeError("MINERU_API_TOKEN not set in .env")

    filename = Path(pdf_path).name

    def log(msg):
        if progress_callback:
            progress_callback(msg)

    # ── Step 1: 申请预签名上传地址，同时携带提取参数 ─────────────────────────
    # 提取参数必须在这一步提交；上传完成后 MinerU 依据这里的配置自动开始提取。
    resp = requests.post(
        f"{MINERU_BASE_URL}/file-urls/batch",
        headers={
            "Authorization": f"Bearer {MINERU_API_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "enable_table": True,
            "enable_formula": False,
            "language": MINERU_LANGUAGE,
            "files": [
                {
                    "name": filename,
                    "is_ocr": True,
                }
            ],
        },
    )
    if not resp.ok:
        raise RuntimeError(
            f"file-urls/batch HTTP {resp.status_code}: {resp.text[:400]}"
        )
    batch_resp = resp.json()
    if batch_resp.get("code") != 0:
        raise RuntimeError(f"file-urls/batch error: {batch_resp}")

    data_block = batch_resp.get("data", {})
    log(f"[debug] file-urls/batch data keys: {list(data_block.keys())}")

    batch_id = data_block.get("batch_id")
    if not batch_id:
        raise RuntimeError(f"No batch_id in: {batch_resp}")

    raw_list = data_block.get("file_urls", [])
    if not raw_list:
        raise RuntimeError(f"file_urls empty in: {batch_resp}")

    # 兼容 string / dict 两种格式
    file_info = raw_list[0]
    if isinstance(file_info, str):
        upload_url = file_info
    elif isinstance(file_info, dict):
        upload_url = (
            file_info.get("url")
            or file_info.get("upload_url")
            or file_info.get("presigned_url")
        )
    else:
        raise RuntimeError(f"Unexpected file_info: {file_info}")

    if not upload_url:
        raise RuntimeError(f"No upload URL in: {file_info}")

    log(f"[debug] batch_id={batch_id}, upload_url prefix={upload_url[:60]}...")

    # ── Step 2: PUT 文件到预签名 URL（签名内嵌在 URL query 里，不加任何 header）──
    # 注意：不要设置 Content-Type，否则会破坏预签名的签名校验导致 403。
    with open(pdf_path, "rb") as f:
        file_bytes = f.read()
    put_resp = requests.put(upload_url, data=file_bytes)
    if not put_resp.ok:
        raise RuntimeError(
            f"OSS PUT failed HTTP {put_resp.status_code}: {put_resp.text[:300]}"
        )
    log("OSS upload OK ✓ — MinerU 将自动开始提取")

    # ── Step 3: 无需再调用 /extract/task/batch，提取已自动触发 ───────────────
    # file-urls/batch 返回的 batch_id 即用于轮询 extract-results/batch。
    return {"mode": "batch", "id": batch_id}


def poll_mineru_task(task_id: str, progress_callback=None) -> dict:
    """Poll single MinerU task until done. Returns result dict."""
    url = f"{MINERU_BASE_URL}/extract/task/{task_id}"
    deadline = time.time() + POLL_TIMEOUT
    headers = {"Authorization": f"Bearer {MINERU_API_TOKEN}"}

    while time.time() < deadline:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()["data"]
        state = data["state"]

        if progress_callback:
            progress_callback(f"MinerU state: {state}")

        if state == "done":
            return data["result"]
        if state == "failed":
            raise RuntimeError(f"MinerU task failed: {data.get('err_msg', 'unknown')}")
        time.sleep(POLL_INTERVAL)

    raise TimeoutError(f"MinerU task {task_id} timed out after {POLL_TIMEOUT}s")


def poll_mineru_batch(batch_id: str, progress_callback=None) -> dict:
    """Poll MinerU batch extraction until done. Returns result dict.

    Actual response structure:
    {"data": {"batch_id": "...", "extract_result": [{"state": "done|failed|running|pending",
                                                       "result": {...}, "err_msg": "..."}]}}
    """
    url = f"{MINERU_BASE_URL}/extract-results/batch/{batch_id}"
    deadline = time.time() + POLL_TIMEOUT
    headers = {"Authorization": f"Bearer {MINERU_API_TOKEN}"}
    first_poll = True

    while time.time() < deadline:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        batch_resp = resp.json()

        if batch_resp.get("code") != 0:
            raise RuntimeError(f"Batch poll error: {batch_resp}")

        batch_data = batch_resp.get("data", {})
        # 实际结构: data.extract_result[0].state（非 data.state）
        extract_results = batch_data.get("extract_result", [])

        if first_poll:
            if progress_callback:
                progress_callback(f"[debug] batch data keys: {list(batch_data.keys())}")
            first_poll = False

        if not extract_results:
            if progress_callback:
                progress_callback("Waiting for extract_result...")
            time.sleep(POLL_INTERVAL)
            continue

        item = extract_results[0]
        state = item.get("state", "unknown")

        if progress_callback:
            progress_callback(f"Batch state: {state}")

        if state == "done":
            # batch 模式返回的是打包 zip（full_zip_url），无单独 content_list_url。
            # 直接把整个 item 交给下载函数，由它决定解 zip 还是取单文件 URL。
            result = item.get("result")
            if result and (result.get("content_list_url") or result.get("full_zip_url")):
                return result
            if item.get("full_zip_url"):
                return item
            raise RuntimeError(f"No result/zip in done item: {item}")

        if state == "failed":
            err = item.get("err_msg") or "unknown"
            raise RuntimeError(f"Batch extraction failed: {err}")

        time.sleep(POLL_INTERVAL)

    raise TimeoutError(f"Batch {batch_id} timed out after {POLL_TIMEOUT}s")


def _download_bytes(url: str, retries: int = 4, timeout: int = 60) -> bytes:
    """GET 二进制内容，带指数退避重试。

    MinerU 的 CDN 偶发 SSLError(UNEXPECTED_EOF) / 连接被重置，多为瞬时问题，
    重试即可恢复。
    """
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.content
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < retries:
                time.sleep(2 ** (attempt - 1))  # 1s, 2s, 4s ...
    raise RuntimeError(
        f"Download failed after {retries} attempts: {url[:80]}... — {last_err}"
    )


def download_mineru_results(result: dict, output_dir: Path) -> Path:
    """Download content_list.json from MinerU result. Returns path.

    支持两种返回形态：
    - single 模式：result 直接带 content_list_url
    - batch 模式：result 只有 full_zip_url，需下载 zip 并从中取出 content_list.json
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    content_list_path = output_dir / "content_list.json"

    # 优先走单文件 URL
    content_list_url = result.get("content_list_url")
    if content_list_url:
        content_list_path.write_bytes(_download_bytes(content_list_url))
        return content_list_path

    # 否则从 full_zip_url 解包
    zip_url = result.get("full_zip_url") or result.get("zip_url")
    if not zip_url:
        raise RuntimeError(f"No content_list_url or zip_url in result: {result}")

    import io
    import zipfile

    zip_bytes = _download_bytes(zip_url)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # zip 内文件名可能带路径前缀，匹配以 content_list.json 结尾的成员
        names = zf.namelist()
        member = next(
            (n for n in names if n.endswith("content_list.json")), None
        )
        if not member:
            raise RuntimeError(
                f"content_list.json not found in zip; members: {names}"
            )
        content_list_path.write_bytes(zf.read(member))

        # 顺带解出其余文件（含图片），便于后续消费
        zf.extractall(output_dir)

    return content_list_path


# LangExtract prompt & examples (KG extraction)
KG_PROMPT = (
    "从文档中提取用于构建知识图谱的结构化信息：\n"
    "1. 实体_组织：机构或公司名称，注明行业与类型；\n"
    "2. 实体_人物：人名，注明职位与所属机构；\n"
    "3. 实体_概念：关键技术术语或产品，注明所属领域；\n"
    "4. 关系：描述两个实体之间关系的文本片段，"
    "   attributes 中注明主体、客体和关系类型（如 '隶属'/'合作'/'研发'）。\n"
    "extraction_text 必须与原文完全一致，不可释义。"
)

KG_EXAMPLES = [
    lx.data.ExampleData(
        text="英伟达CEO黄仁勋表示，数据中心业务收入达到226亿美元，同比增长154%。",
        extractions=[
            lx.data.Extraction(
                extraction_class="实体_组织",
                extraction_text="英伟达",
                attributes={"行业": "半导体/AI芯片", "类型": "上市公司"},
            ),
            lx.data.Extraction(
                extraction_class="实体_人物",
                extraction_text="黄仁勋",
                attributes={"职位": "CEO", "所属机构": "英伟达"},
            ),
            lx.data.Extraction(
                extraction_class="关系",
                extraction_text="英伟达CEO黄仁勋",
                attributes={"主体": "黄仁勋", "客体": "英伟达", "关系类型": "隶属"},
            ),
        ],
    )
]


def stream_processing(job_id: str):
    """Generator for SSE stream. Yields JSON events."""

    def emit(event_type: str, data: dict = None, message: str = None):
        payload = {"type": event_type}
        if data:
            payload.update(data)
        if message:
            payload["message"] = message
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    try:
        job = jobs.get(job_id)
        if not job:
            yield from emit("error", message="Job not found")
            return

        pdf_path = job["pdf_path"]
        task_meta = job.get("task_meta")  # {"mode": "batch"|"single", "id": "..."}

        # Stage 1: Submit to MinerU (if not already done)
        if not task_meta:
            yield from emit("stage", {"stage": "mineru", "status": "starting"})

            # 将 progress 信息转发到 SSE 流
            messages_buffer = []
            def mineru_log(msg):
                messages_buffer.append(msg)

            try:
                task_meta = submit_mineru_task(pdf_path, progress_callback=mineru_log)
                job["task_meta"] = task_meta
                for msg in messages_buffer:
                    yield from emit("progress", message=msg)
                yield from emit(
                    "progress",
                    message=f"MinerU task submitted ({task_meta['mode']}): {task_meta['id']}",
                )
            except Exception as e:
                for msg in messages_buffer:
                    yield from emit("progress", message=msg)
                yield from emit("error", message=f"MinerU submit failed: {str(e)}")
                return

        task_mode = task_meta["mode"]
        task_id = task_meta["id"]

        # Poll MinerU — 根据模式选择轮询接口
        yield from emit("progress", message=f"Polling MinerU ({task_mode})...")
        try:
            if task_mode == "batch":
                result = poll_mineru_batch(
                    task_id,
                    lambda msg: emit("progress", message=msg)
                )
            else:
                result = poll_mineru_task(
                    task_id,
                    lambda msg: emit("progress", message=msg)
                )
            yield from emit("stage", {"stage": "mineru", "status": "done"})
        except Exception as e:
            yield from emit("error", message=f"MinerU poll failed: {str(e)}")
            return

        # Download content_list.json
        mineru_output_dir = OUTPUT_DIR / task_id[:8]
        try:
            content_list_path = download_mineru_results(result, mineru_output_dir)
            yield from emit("progress", message=f"Downloaded content_list.json")
        except Exception as e:
            yield from emit("error", message=f"Download failed: {str(e)}")
            return

        # Stage 2: Bridge Layer
        yield from emit("stage", {"stage": "bridge", "status": "starting"})
        try:
            pdf_stem = Path(pdf_path).stem
            documents = content_list_to_documents(
                str(content_list_path), pdf_stem, split_by="page"
            )
            yield from emit(
                "progress", message=f"Bridge: converted {len(documents)} documents"
            )
            yield from emit("stage", {"stage": "bridge", "status": "done"})
        except Exception as e:
            yield from emit("error", message=f"Bridge failed: {str(e)}")
            return

        # Stage 3: LangExtract
        yield from emit("stage", {"stage": "extract", "status": "starting"})
        if not OPENAI_API_KEY:
            yield from emit("error", message="OPENAI_API_KEY not set in .env")
            return

        try:
            model = OpenAILanguageModel(
                model_id=DEEPSEEK_MODEL,
                api_key=OPENAI_API_KEY,
                base_url=DEEPSEEK_BASE_URL,
                temperature=0.0,
            )

            extraction_count = 0
            all_annotated_docs = []

            for doc in documents:
                result = lx.extract(
                    text_or_documents=[doc],
                    prompt_description=KG_PROMPT,
                    examples=KG_EXAMPLES,
                    model=model,
                    max_char_buffer=2000,
                    context_window_chars=300,
                    show_progress=False,
                    debug=True,
                )
                annotated_doc = result[0]
                all_annotated_docs.append(annotated_doc)

                doc_extractions = annotated_doc.extractions or []
                yield from emit("progress", message=f"doc '{annotated_doc.document_id}': {len(doc_extractions)} extractions")

                # Stream each extraction
                for extraction in doc_extractions:
                    extraction_count += 1
                    extraction_dict = {
                        "extraction_class": extraction.extraction_class,
                        "extraction_text": extraction.extraction_text,
                        "attributes": extraction.attributes or {},
                        "char_interval": {"start_pos": extraction.char_interval.start_pos, "end_pos": extraction.char_interval.end_pos}
                        if extraction.char_interval
                        else None,
                    }
                    yield from emit("extraction", {"data": extraction_dict})

            yield from emit(
                "progress",
                message=f"LangExtract: {extraction_count} extractions completed",
            )
            yield from emit("stage", {"stage": "extract", "status": "done"})

            # Stage 4: Build Knowledge Graph
            yield from emit("stage", {"stage": "graph", "status": "starting"})
            graph = build_knowledge_graph(all_annotated_docs, pdf_stem)
            graph_path = OUTPUT_DIR / job_id / "knowledge_graph.json"
            graph_path.parent.mkdir(parents=True, exist_ok=True)
            save_knowledge_graph(graph, str(graph_path))

            job["graph"] = graph
            yield from emit(
                "graph",
                {
                    "data": {
                        "nodes": graph["nodes"],
                        "edges": graph["edges"],
                        "meta": graph["meta"],
                    }
                },
            )
            yield from emit("stage", {"stage": "graph", "status": "done"})
            yield from emit("complete")

        except Exception as e:
            yield from emit("error", message=f"LangExtract failed: {str(e)}")
            return

    except Exception as e:
        yield from emit("error", message=f"Unexpected error: {str(e)}")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload_pdf():
    """Receive PDF, submit to MinerU, return job_id."""
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files allowed"}), 400

    # Save uploaded file
    pdf_path = UPLOAD_DIR / file.filename
    file.save(str(pdf_path))

    # Create job
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "pdf_path": str(pdf_path),
        "task_id": None,
        "status": "pending",
    }

    return jsonify({"job_id": job_id, "filename": file.filename}), 200


@app.route("/api/stream/<job_id>")
def stream(job_id: str):
    """SSE endpoint for streaming processing updates."""
    return Response(
        stream_processing(job_id),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/graph/<job_id>")
def get_graph(job_id: str):
    """Return complete knowledge graph JSON."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    graph = job.get("graph")
    if not graph:
        return jsonify({"error": "Graph not ready"}), 202  # Accepted, processing

    return jsonify(graph), 200


@app.route("/api/url-extract", methods=["POST"])
def url_extract():
    """Submit a public PDF URL directly to MinerU (bypasses file upload)."""
    data = request.get_json(silent=True) or {}
    pdf_url = data.get("url", "").strip()
    if not pdf_url:
        return jsonify({"error": "url is required"}), 400
    if not MINERU_API_TOKEN:
        return jsonify({"error": "MINERU_API_TOKEN not configured"}), 500

    # Submit to MinerU single-task API with JSON body
    resp = requests.post(
        f"{MINERU_BASE_URL}/extract/task",
        headers={
            "Authorization": f"Bearer {MINERU_API_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "url": pdf_url,
            "is_ocr": True,
            "enable_table": True,
            "enable_formula": False,
            "language": MINERU_LANGUAGE,
        },
    )
    if not resp.ok:
        return jsonify({"error": f"MinerU HTTP {resp.status_code}: {resp.text[:300]}"}), 502
    body = resp.json()
    if body.get("code") != 0:
        return jsonify({"error": f"MinerU error: {body}"}), 502

    task_id = body["data"]["task_id"]
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "pdf_path": pdf_url,
        "task_meta": {"mode": "single", "id": task_id},
        "status": "pending",
    }
    return jsonify({"job_id": job_id, "task_id": task_id}), 200


@app.route("/api/upload-content-list", methods=["POST"])
def upload_content_list():
    """Skip MinerU — upload content_list.json directly to start from Bridge stage."""
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files["file"]
    if not file.filename.lower().endswith(".json"):
        return jsonify({"error": "Only JSON files allowed"}), 400

    stem = request.form.get("stem", "document")
    cl_path = UPLOAD_DIR / f"content_list_{uuid.uuid4().hex[:6]}.json"
    file.save(str(cl_path))

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "content_list_path": str(cl_path),
        "pdf_stem": stem,
        "mode": "direct",
        "status": "pending",
    }
    return jsonify({"job_id": job_id, "filename": file.filename}), 200


def stream_direct(job_id: str):
    """SSE generator for direct content_list.json mode (skips MinerU)."""

    def emit(event_type: str, data: dict = None, message: str = None):
        payload = {"type": event_type}
        if data:
            payload.update(data)
        if message:
            payload["message"] = message
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    try:
        job = jobs.get(job_id)
        if not job:
            yield from emit("error", message="Job not found")
            return

        content_list_path = job["content_list_path"]
        pdf_stem = job.get("pdf_stem", "document")

        # Stage 1: skip MinerU
        yield from emit("stage", {"stage": "mineru", "status": "done"})
        yield from emit("progress", message="MinerU stage skipped (direct content_list mode)")

        # Stage 2: Bridge
        yield from emit("stage", {"stage": "bridge", "status": "starting"})
        try:
            documents = content_list_to_documents(content_list_path, pdf_stem, split_by="page")
            yield from emit("progress", message=f"Bridge: {len(documents)} documents")
            yield from emit("stage", {"stage": "bridge", "status": "done"})
        except Exception as e:
            yield from emit("error", message=f"Bridge failed: {e}")
            return

        # Stage 3: LangExtract
        yield from emit("stage", {"stage": "extract", "status": "starting"})
        if not OPENAI_API_KEY:
            yield from emit("error", message="OPENAI_API_KEY not set")
            return
        try:
            model = OpenAILanguageModel(
                model_id=DEEPSEEK_MODEL, api_key=OPENAI_API_KEY,
                base_url=DEEPSEEK_BASE_URL, temperature=0.0,
            )
            all_annotated = []
            count = 0
            for doc in documents:
                res = lx.extract(
                    text_or_documents=[doc], prompt_description=KG_PROMPT,
                    examples=KG_EXAMPLES, model=model,
                    max_char_buffer=2000, context_window_chars=300,
                    show_progress=False, debug=True,
                )
                annotated_doc = res[0]
                all_annotated.append(annotated_doc)
                for ext in (annotated_doc.extractions or []):
                    count += 1
                    yield from emit("extraction", {"data": {
                        "extraction_class": ext.extraction_class,
                        "extraction_text": ext.extraction_text,
                        "attributes": ext.attributes or {},
                        "char_interval": {"start_pos": ext.char_interval.start_pos, "end_pos": ext.char_interval.end_pos} if ext.char_interval else None,
                    }})
            yield from emit("progress", message=f"LangExtract: {count} extractions")
            yield from emit("stage", {"stage": "extract", "status": "done"})

            # Stage 4: Graph
            yield from emit("stage", {"stage": "graph", "status": "starting"})
            graph = build_knowledge_graph(all_annotated, pdf_stem)
            graph_path = OUTPUT_DIR / job_id / "knowledge_graph.json"
            graph_path.parent.mkdir(parents=True, exist_ok=True)
            save_knowledge_graph(graph, str(graph_path))
            job["graph"] = graph
            yield from emit("graph", {"data": {"nodes": graph["nodes"],
                                                "edges": graph["edges"],
                                                "meta": graph["meta"]}})
            yield from emit("stage", {"stage": "graph", "status": "done"})
            yield from emit("complete")
        except Exception as e:
            yield from emit("error", message=f"Extract/Graph failed: {e}")
    except Exception as e:
        yield from emit("error", message=f"Unexpected error: {e}")


@app.route("/api/stream-direct/<job_id>")
def stream_direct_route(job_id: str):
    """SSE for direct content_list mode."""
    return Response(
        stream_direct(job_id),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


if __name__ == "__main__":
    print("🕸️  BridgePipeline Visualization Server")
    print("📝  Starting Flask on http://localhost:8080")
    app.run(debug=True, host="0.0.0.0", port=8080)
