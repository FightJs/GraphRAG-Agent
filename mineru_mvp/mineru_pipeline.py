"""
MinerU Cloud API MVP Pipeline
Flow: local PDF → multipart upload → poll status → download results
"""

import os
import sys
import time
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["MINERU_API_TOKEN"]
BASE_URL = os.environ.get("MINERU_BASE_URL", "https://mineru.net/api/v4")
LANGUAGE = os.environ.get("MINERU_LANGUAGE", "ch")
OCR_ENABLE = os.environ.get("MINERU_OCR_ENABLE", "true")
ENABLE_TABLE = os.environ.get("MINERU_ENABLE_TABLE", "true")
ENABLE_FORMULA = os.environ.get("MINERU_ENABLE_FORMULA", "false")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "3"))
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", "300"))

AUTH = {"Authorization": f"Bearer {TOKEN}"}
RESULTS_DIR = Path("results")


def submit_task(pdf_path: Path) -> str:
    """Upload local PDF via multipart and return task_id."""
    with open(pdf_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/extract/task",
            headers=AUTH,
            files={"file": (pdf_path.name, f, "application/pdf")},
            data={
                "is_ocr_enable": OCR_ENABLE,
                "enable_table": ENABLE_TABLE,
                "enable_formula": ENABLE_FORMULA,
                "language": LANGUAGE,
            },
        )
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(f"Submit failed (code={body.get('code')}): {body}")
    return body["data"]["task_id"]


def poll_task(task_id: str) -> dict:
    """Poll until state=done or failed, return result dict."""
    url = f"{BASE_URL}/extract/task/{task_id}"
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        resp = requests.get(url, headers=AUTH)
        resp.raise_for_status()
        data = resp.json()["data"]
        state = data["state"]
        print(f"  [{time.strftime('%H:%M:%S')}] state = {state}")
        if state == "done":
            return data["result"]
        if state == "failed":
            raise RuntimeError(f"Task failed: {data.get('err_msg', 'unknown')}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Timed out after {POLL_TIMEOUT}s (task_id={task_id})")


def download_results(result: dict, output_dir: Path) -> None:
    """Download markdown + content_list JSON and save task metadata."""
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = {
        "output.md": result.get("markdown_url"),
        "content_list.json": result.get("content_list_url"),
    }
    for name, url in targets.items():
        if not url:
            print(f"  [skip] {name} — URL not available")
            continue
        r = requests.get(url)
        r.raise_for_status()
        (output_dir / name).write_bytes(r.content)
        size = len(r.content)
        print(f"  Saved {name}  ({size:,} bytes)")

    (output_dir / "task_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Saved task_result.json")


def show_content_summary(output_dir: Path) -> None:
    """Print a brief summary of the parsed content_list.json."""
    content_file = output_dir / "content_list.json"
    if not content_file.exists():
        return
    blocks = json.loads(content_file.read_text(encoding="utf-8"))
    from collections import Counter
    counts = Counter(b.get("type") for b in blocks)
    print("\n  Content block summary:")
    for btype, count in counts.most_common():
        print(f"    {btype:<20} {count} block(s)")


def run_pipeline(pdf_path: str) -> None:
    pdf = Path(pdf_path)
    if not pdf.exists():
        raise FileNotFoundError(f"PDF not found: {pdf}")

    size_kb = pdf.stat().st_size // 1024
    print(f"\n[1/3] Submitting  {pdf.name}  ({size_kb} KB)")
    task_id = submit_task(pdf)
    print(f"      task_id = {task_id}")

    print(f"\n[2/3] Polling  (interval={POLL_INTERVAL}s, timeout={POLL_TIMEOUT}s)")
    result = poll_task(task_id)

    output_dir = RESULTS_DIR / task_id[:8]
    print(f"\n[3/3] Downloading results → {output_dir}/")
    download_results(result, output_dir)
    show_content_summary(output_dir)

    print(f"\nDone.")
    print(f"  output.md         → {output_dir}/output.md")
    print(f"  content_list.json → {output_dir}/content_list.json")
    print(f"  task_result.json  → {output_dir}/task_result.json")


if __name__ == "__main__":
    pdf_arg = sys.argv[1] if len(sys.argv) > 1 else "sample.pdf"
    run_pipeline(pdf_arg)
