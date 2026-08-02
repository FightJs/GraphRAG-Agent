# MinerU Cloud API I/O 规范文档 v1.0

> 版本：v1.0（2026-07-30）  
> 基于官方文档（mineru.net/apiManage/docs）与 MVP 测试代码对比整理  
> 原始参考：`docs/mineru_cloud_api_spec.md`  
> 测试脚本路径：`mineru_mvp/`（项目根目录下）

---

## 一、Pipeline 执行流程

### 1.1 测试脚本目录结构

```
GraphRAG-Agent/
└── mineru_mvp/
    ├── .venv/                     # uv 虚拟环境（不提交 git，需先激活）
    ├── CLAUDE.md                  # Claude Code 工作规范（环境隔离说明）
    ├── .env                       # API Token、Base URL、解析参数
    ├── requirements.txt           # 依赖：requests, python-dotenv, fpdf2
    ├── create_sample_pdf.py       # 生成含标题/段落/表格的示例 PDF
    ├── mineru_pipeline.py         # 完整 Pipeline 入口
    └── results/                   # 运行后自动创建
        └── {task_id_prefix_8}/
            ├── output.md          # Markdown 正文
            ├── content_list.json  # 结构化 JSON（GraphRAG 直接输入）
            └── task_result.json   # 完整 API 响应元数据
```

### 1.2 Pipeline 执行步骤

```
本地 PDF 文件
    │
    ▼  multipart/form-data 上传
[Step 1] POST /api/v4/extract/task
    │
    ▼  返回 task_id
[Step 2] GET /api/v4/extract/task/{task_id}
         轮询 state：pending → running → done | failed
    │
    ▼  state=done，result 含 CDN 下载链接
[Step 3] 下载并保存到 results/{task_id[:8]}/
         output.md + content_list.json + task_result.json
```

### 1.3 快速运行命令

> ⚠️ **环境隔离要求**：本组件使用独立 uv 虚拟环境，必须在激活后再执行任何操作，避免与 LangExtract、GraphRAG 等组件的依赖冲突。

**Step 0：首次使用——创建并安装依赖**

```bash
cd mineru_mvp

# 创建虚拟环境（仅首次需要）
uv venv .venv

# 激活虚拟环境
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

# 确认激活（提示符前应显示 (.venv)）
which python
# → .../mineru_mvp/.venv/bin/python

# 安装依赖（激活后执行）
uv pip install -r requirements.txt
```

**Step 1：后续每次运行——先激活虚拟环境**

```bash
cd mineru_mvp
source .venv/bin/activate          # 每次新开终端必须执行

python create_sample_pdf.py        # 生成 sample.pdf
python mineru_pipeline.py          # 运行完整 Pipeline
# 指定其他文件：python mineru_pipeline.py path/to/your.pdf
```

**退出虚拟环境：**

```bash
deactivate
```

**注意事项：**

| 场景 | 说明 |
|---|---|
| 新开终端 | 每次需重新执行 `source .venv/bin/activate` |
| 提示符无 `(.venv)` | 说明未激活，不要直接运行脚本 |
| 依赖缺失报错 | 先激活 venv，再执行 `uv pip install -r requirements.txt` |
| 与其他组件共存 | 各组件使用独立 venv，不要在根目录或其他 venv 中运行本组件脚本 |

---

## 二、API 端点规范（精准解析 Precision API）

### 2.1 基础信息

| 项目 | 值 |
|---|---|
| Base URL | `https://mineru.net/api/v4` |
| 认证方式 | Bearer Token（mineru.net 注册后获取） |
| 请求格式 | `application/json` 或 `multipart/form-data`（文件上传） |
| 响应格式 | `application/json` |
| 任务模型 | **异步**：提交任务 → task_id → 轮询状态 → 下载结果 |

### 2.2 端点列表

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v4/extract/task` | 提交单文件解析任务（URL 或 multipart） |
| GET | `/api/v4/extract/task/{task_id}` | 查询单任务状态与结果 |
| POST | `/api/v4/file-urls/batch` | 批量本地文件上传，获取临时访问 URL |
| POST | `/api/v4/extract/task/batch` | 批量 URL 提交解析任务 |
| GET | `/api/v4/extract-results/batch/{batch_id}` | 查询批量任务结果 |

### 2.3 提交单文件解析任务

```
POST /api/v4/extract/task
Authorization: Bearer <TOKEN>
```

**方式一：JSON + 公网 URL**

```json
{
  "url": "https://your-cdn.com/document.pdf",
  "model_version": "pipeline",
  "is_ocr": true,
  "enable_table": true,
  "enable_formula": false,
  "language": "ch",
  "page_ranges": "1-10",
  "extra_formats": ["docx"],
  "callback_url": "https://your-server.com/webhook/mineru"
}
```

**方式二：multipart/form-data（本地文件直传，MVP 测试采用此方式）**

```
Content-Type: multipart/form-data
file         = <binary PDF>
model_version = "pipeline"
is_ocr        = "true"
enable_table  = "true"
enable_formula= "false"
language      = "ch"
```

> multipart 方式中，布尔值以字符串形式传递（`"true"` / `"false"`），不可用 Python bool 类型。

**成功响应（HTTP 200）：**

```json
{
  "code": 0,
  "msg": "ok",
  "trace_id": "abc123xyz",
  "data": {
    "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }
}
```

### 2.4 请求参数详解

| 参数 | 类型 | 必填 | 默认值 | 取值范围 | 说明 |
|---|---|---|---|---|---|
| `url` | string | 是* | — | 公网 URL | 文件公网地址；与 multipart 文件上传二选一 |
| `model_version` | string | 否 | `"pipeline"` | `pipeline` / `vlm` / `MinerU-HTML` | 解析模型（详见下表） |
| `is_ocr` | boolean | 否 | `true` | `true` / `false` | 是否启用 OCR；扫描件必须为 `true` |
| `enable_table` | boolean | 否 | `true` | `true` / `false` | 是否识别并导出表格 |
| `enable_formula` | boolean | 否 | `true` | `true` / `false` | 是否识别数学公式（输出 LaTeX） |
| `language` | string | 否 | `"ch"` | 见附录语言表 | 文档主要语言，影响 OCR 精度 |
| `page_ranges` | string | 否 | 全文 | `"1-10"` / `"2,4-6"` | 指定解析页码范围（**1-indexed**） |
| `extra_formats` | array | 否 | `[]` | `"docx"` / `"html"` / `"latex"` | 额外导出格式，追加至 zip 包中 |
| `callback_url` | string | 否 | — | 合法 HTTP(S) URL | 任务完成后的 Webhook 回调地址 |

> ⚠️ **v1.0 勘误**：
> - 原规范参数 `is_ocr_enable` 已更名为 **`is_ocr`**
> - 原规范 `page_start`/`page_end`（整数）已替换为 **`page_ranges`**（字符串，如 `"1-10"`）
> - 新增参数 `model_version`、`extra_formats`（原规范缺失）

**`model_version` 取值说明：**

| 值 | 说明 | 适用场景 |
|---|---|---|
| `pipeline` | 传统多阶段 Pipeline（默认） | 通用文档，速度较快 |
| `vlm` | 视觉语言模型 | 复杂图文混排、手写体、低质量扫描件 |
| `MinerU-HTML` | HTML 结构化输出 | 需要 HTML 树形结构的下游处理 |

### 2.5 文件规格限制

| 限制项 | 精准解析 API | 轻量解析 API |
|---|---|---|
| 最大文件大小 | 200 MB | 10 MB |
| 最大页数 | **200 页** | 20 页 |
| 支持格式 | PDF / DOCX / PPTX / XLSX / 图片 / HTML | PDF / DOCX / PPTX / XLSX / 图片 |
| 批量上限 | 200 文件/次 | — |

> ⚠️ **v1.0 勘误**：原规范最大页数记录为 **600 页**，官方文档实际限制为 **200 页**。

---

## 三、任务状态与响应结构

### 3.1 任务状态枚举

| 值 | 含义 |
|---|---|
| `pending` | 已入队，等待处理 |
| `running` | 解析进行中 |
| `done` | 解析完成，`result` 中包含 CDN 下载链接 |
| `failed` | 解析失败，`err_msg` 中包含错误原因 |

> ⚠️ **v1.0 勘误**：原规范状态值 `processing` 已更正为 **`running`**。

### 3.2 通用响应结构

```json
{
  "code": 0,
  "msg": "ok",
  "trace_id": "string",
  "data": {}
}
```

### 3.3 任务状态查询响应（state=done）

```
GET /api/v4/extract/task/{task_id}
```

```json
{
  "code": 0,
  "data": {
    "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "state": "done",
    "err_msg": "",
    "result": {
      "markdown_url":      "https://cdn.mineru.net/.../output.md",
      "zip_url":           "https://cdn.mineru.net/.../output.zip",
      "content_list_url":  "https://cdn.mineru.net/.../content_list.json",
      "model_url":         "https://cdn.mineru.net/.../model.json",
      "middle_url":        "https://cdn.mineru.net/.../middle.json",
      "layout_pdf_url":    "https://cdn.mineru.net/.../layout.pdf"
    }
  }
}
```

### 3.4 常见错误码

| HTTP 状态 | `code` | 含义 |
|---|---|---|
| 200 | 0 | 成功 |
| 400 | 1001 | 请求参数不合法 |
| 401 | 1002 | Token 无效或过期 |
| 429 | 1003 | 请求速率超限 |
| 500 | 1004 | 服务端内部错误 |
| 200 | 2001 | 文件解析失败（格式不支持或文件损坏） |

---

## 四、输出文件规范

### 4.1 API result 字段与文件清单

任务完成后，`data.result` 对象包含以下 CDN 下载链接：

| result 字段 | 文件名 | 说明 | MVP 必读 |
|---|---|---|---|
| `markdown_url` | `output.md` | 完整 Markdown 正文，含表格/公式 | 是 |
| `content_list_url` | `content_list.json` | 结构化内容块数组 | **核心** |
| `zip_url` | `output.zip` | 全量打包（含提取图片等） | 含图片时必须 |
| `middle_url` | `middle.json` | 完整分层结构（页→块→行→字符） | 按需 |
| `model_url` | `model.json` | 原始视觉模型检测框与置信度 | 调试用 |
| `layout_pdf_url` | `layout.pdf` | 布局可视化（含阅读顺序编号） | 调试用 |

### 4.2 本地 Pipeline 实际生成文件

Pipeline 运行后下载至 `mineru_mvp/results/{task_id[:8]}/`：

| 本地文件 | 来源 | 说明 |
|---|---|---|
| `output.md` | `markdown_url` | Markdown 正文，可直接阅读 |
| `content_list.json` | `content_list_url` | 结构化 JSON，GraphRAG 知识库直接输入 |
| `task_result.json` | 本地保存 | 完整 API result 元数据，含全部 CDN 链接备用 |

> `model.json`、`middle.json`、`layout.pdf`、`output.zip` 在 MVP 阶段按需手动下载，  
> 链接均保存在 `task_result.json` 中，可随时取用。

### 4.3 content_list.json 字段说明

顶层结构为 JSON 数组，每个元素为一个 ContentBlock：

```json
[
  {
    "type": "text",
    "content": "## 第一章 绪论",
    "page_idx": 0,
    "bbox": [73, 120, 521, 145],
    "text_level": 1
  },
  {
    "type": "table",
    "content": "<table>...</table>",
    "page_idx": 1,
    "bbox": [60, 200, 540, 450],
    "table_caption": "表1 各组实验结果对比",
    "table_footnote": "注：数据来源于2024年实测"
  },
  {
    "type": "image",
    "content": "",
    "page_idx": 2,
    "bbox": [80, 300, 480, 600],
    "img_path": "images/page2_fig1.png",
    "img_caption": "图1 系统架构图"
  }
]
```

**字段清单：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | string | 内容块类型（枚举见下表） |
| `content` | string | 块的文本内容（Markdown 格式）；图片块为空字符串 |
| `page_idx` | integer | 所在页码，**0-indexed** |
| `bbox` | `[x0, y0, x1, y1]` | 归一化坐标（0–1000），左上角原点，x 右增，y 下增 |
| `text_level` | integer | 文本层级：`0`=正文，`1`=H1，`2`=H2，`3`=H3（仅 `type=text`） |
| `img_path` | string | 图片相对路径（相对 zip 根目录），仅 `type=image` |
| `img_caption` | string | 图注文字，仅 `type=image` |
| `table_caption` | string | 表标题，仅 `type=table` |
| `table_footnote` | string | 表脚注，仅 `type=table` |
| `equation_content` | string | LaTeX 公式原文，仅 `type=equation` / `interline_equation` |

**`type` 枚举值：**

| 值 | 含义 | `content` 格式 |
|---|---|---|
| `text` | 普通文本或标题 | Markdown 字符串 |
| `table` | 表格 | HTML `<table>` 或 Markdown 表格 |
| `image` | 嵌入图片 | 空字符串，路径见 `img_path` |
| `equation` | 行内数学公式 | LaTeX（不含 `$` 分隔符） |
| `interline_equation` | 独立行数学公式 | LaTeX（不含 `$$` 分隔符） |
| `code` | 代码块 | 原始代码字符串 |
| `list` | 有序/无序列表 | Markdown 列表字符串 |

### 4.4 坐标系说明

| 文件 | 坐标范围 | 原点 | 备注 |
|---|---|---|---|
| `content_list.json` | 0–1000（归一化） | 左上角 | 1000 对应页面宽/高 |
| `middle.json` | 原始 pt 值 | 左上角 | `page_size` 提供参考宽高 |
| `model.json` | 原始像素值 | 左上角 | `page_info.width/height` 提供参考 |

归一化坐标换算（content_list.json → 实际 pt）：

```python
x0_pt = bbox[0] / 1000 * page_w
y0_pt = bbox[1] / 1000 * page_h
x1_pt = bbox[2] / 1000 * page_w
y1_pt = bbox[3] / 1000 * page_h
```

---

## 五、推荐轮询策略

状态流转：`pending` → `running` → `done` | `failed`

```python
import os, time, requests

def poll_task(task_id: str, interval: int = 3, timeout: int = 300) -> dict:
    headers = {"Authorization": f"Bearer {os.environ['MINERU_API_TOKEN']}"}
    url = f"https://mineru.net/api/v4/extract/task/{task_id}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = requests.get(url, headers=headers).json()["data"]
        state = data["state"]
        if state == "done":
            return data["result"]
        if state == "failed":
            raise RuntimeError(data.get("err_msg", "unknown"))
        time.sleep(interval)
    raise TimeoutError(f"Task {task_id} timed out after {timeout}s")
```

> MVP 推荐参数：`interval=3`，`timeout=300`；大文件可适当调大 timeout。

---

## 六、轻量解析 API（Agent Lightweight API）

### 6.1 基础信息

| 项目 | 值 |
|---|---|
| Base URL | `https://mineru.net/api/v1` |
| 认证方式 | **无需**（IP 级限速） |
| 最大文件 | 10 MB / 20 页 |
| 输出内容 | Markdown only（无 `content_list.json`） |
| 适用场景 | 快速验证，**不推荐用于生产级数据提取** |

### 6.2 端点列表

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/agent/parse/url` | URL 文件解析 |
| POST | `/api/v1/agent/parse/file` | 本地文件上传解析 |
| GET | `/api/v1/agent/parse/{task_id}` | 查询解析结果 |

### 6.3 请求参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `url` / `file_name` | string | 是 | URL 或文件名（二选一） |
| `page_range` | string | 否 | 仅 PDF 有效，格式 `"1-10"` |
| `enable_table` | boolean | 否 | 是否识别表格 |
| `is_ocr` | boolean | 否 | 是否启用 OCR |
| `enable_formula` | boolean | 否 | 是否识别公式 |

---

## 七、v1.0 勘误汇总

原规范（`docs/mineru_cloud_api_spec.md`）与 v1.0 的差异对照：

| 原规范内容 | v1.0 更正 | 依据 |
|---|---|---|
| `state` 含 `processing` | 更正为 **`running`** | 官方文档 |
| 最大页数 **600 页** | 更正为 **200 页** | 官方文档 |
| 参数 `is_ocr_enable` | 更正为 **`is_ocr`** | 官方文档 |
| `page_start`/`page_end`（整数） | 替换为 **`page_ranges`**（字符串 `"1-10"`） | 官方文档 |
| 缺少 `model_version` 参数 | 补充三值枚举：`pipeline`/`vlm`/`MinerU-HTML` | 官方文档 |
| 缺少 `extra_formats` 参数 | 补充数组参数：`docx`/`html`/`latex` | 官方文档 |
| 缺少批量上传端点 | 补充 `POST /api/v4/file-urls/batch` | 官方文档 |
| 缺少批量结果查询端点 | 补充 `GET /api/v4/extract-results/batch/{batch_id}` | 官方文档 |
| 响应缺少 `trace_id` 字段 | 补充通用响应字段 `trace_id` | 官方文档 |
| 本地 Pipeline 流程未记录 | 补充 `mineru_mvp/` 目录结构与执行步骤 | 实测代码 |
| 结果文件仅描述 CDN 链接 | 补充本地保存路径与 `task_result.json` 说明 | 实测代码 |

---

## 附录

### A. 常用语言代码

| 代码 | 语言 |
|---|---|
| `ch` | 中文（简体） |
| `cht` | 中文（繁体） |
| `en` | 英文 |
| `japan` | 日文 |
| `korean` | 韩文 |
| `fr` | 法文 |
| `de` | 德文 |

> 完整列表参见 MinerU 官方文档：[opendatalab.github.io/MinerU](https://opendatalab.github.io/MinerU)

### B. .env 配置参考

```ini
# MinerU Cloud API
MINERU_API_TOKEN=<your_token_here>
MINERU_BASE_URL=https://mineru.net/api/v4

# 解析参数
MINERU_LANGUAGE=ch
MINERU_OCR_ENABLE=true
MINERU_ENABLE_TABLE=true
MINERU_ENABLE_FORMULA=false

# 轮询
POLL_INTERVAL=3
POLL_TIMEOUT=300
```

### C. 相关文件路径速查

| 文件 | 路径 |
|---|---|
| 原始规范 | `docs/mineru_cloud_api_spec.md` |
| 当前规范（v1.0） | `docs/mineru_cloud_api_io_spec_v1.0.md` |
| Pipeline 入口 | `mineru_mvp/mineru_pipeline.py` |
| 环境配置 | `mineru_mvp/.env` |
| 示例 PDF 生成 | `mineru_mvp/create_sample_pdf.py` |
| 解析结果输出目录 | `mineru_mvp/results/{task_id[:8]}/` |

---

*Sources: [MinerU 官方 API 文档](https://mineru.net/apiManage/docs) · [MinerU 输出文件格式](https://opendatalab.github.io/MinerU/zh/reference/output_files/)*
