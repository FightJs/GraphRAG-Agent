# BridgePipeline 接口规范文档 v1.0

> 版本：v1.0（2026-07-31）
> 组件角色：GraphRAG 索引阶段核心数据流水线
> 上游：MinerU Cloud API（PDF 解析）
> 下游：LangExtract（结构化信息提取）→ 知识图谱构建
> 参数依据：`mineru_pipeline.py` 源码 + `langextract/output/deepseek_result.jsonl` 实际输出

---

## 一、Pipeline 总体执行流程

### 1.1 三阶段架构

```
┌─────────────────────────────────────────────────────────────────┐
│  Stage 1：MinerU Pipeline                                        │
│  本地 PDF ──multipart 上传──▶ MinerU Cloud API ──轮询──▶         │
│  results/{task_id[:8]}/content_list.json                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │  content_list.json（JSON 块数组）
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Stage 2：Bridge Layer（mineru_to_text.py）                      │
│  过滤块类型 → HTML table 转 Markdown → 按页拼接文本              │
│  → List[lx.data.Document]                                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │  List[lx.data.Document]（纯文本）
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Stage 3：LangExtract Pipeline（langextract_kg.py）              │
│  lx.extract() → AnnotatedDocument → kg_result.jsonl            │
│  → knowledge_graph.json（节点 + 边）                            │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 目录结构与测试脚本存放位置

```
GraphRAG-Agent/
├── mineru_mvp/                        # Stage 1：PDF 解析组件
│   ├── .venv/                         # 独立虚拟环境（uv 创建）
│   ├── CLAUDE.md
│   ├── .env
│   ├── requirements.txt
│   ├── create_sample_pdf.py           # 示例 PDF 生成
│   ├── mineru_pipeline.py             # ★ MinerU Pipeline 入口脚本
│   └── results/{task_id[:8]}/
│       ├── content_list.json          # ★ Stage 1 核心输出
│       ├── output.md
│       └── task_result.json
│
├── bridge_pipeline/                   # Stage 2 + Stage 3：对接与提取组件
│   ├── .venv/                         # 独立虚拟环境（继承 langextract 依赖）
│   ├── CLAUDE.md                      # ★ 本组件工作规范
│   ├── .env                           # API Key 及模型配置
│   ├── mineru_to_text.py              # ★ Bridge 层（Stage 2）
│   ├── langextract_kg.py              # ★ KG 提取入口（Stage 3）
│   ├── graph_builder.py               # 知识图谱构建
│   └── output/
│       ├── kg_result.jsonl            # ★ Stage 3 提取结果（JSONL）
│       ├── kg_result.html             # 可视化
│       └── knowledge_graph.json       # 最终知识图谱
│
├── langextract/                       # LangExtract 库（Stage 3 依赖）
│   ├── .venv/
│   ├── CLAUDE.md
│   └── output/
│       ├── deepseek_result.jsonl      # ★ 实际验证输出（规范依据）
│       └── deepseek_result.html
│
└── docs/
    ├── bridgepipeline-spec-v1.0.md    # ★ 本文件
    ├── langextract_spec-v1.0.md
    └── mineru_cloud_api_io_spec_v1.0.md
```

---

## 二、MinerU Pipeline 关键参数规范

### 2.1 环境变量参数（`mineru_mvp/.env`）

基于 `mineru_pipeline.py` 源码实际读取逻辑：

| 环境变量 | 必填 | 默认值 | 类型 | 说明 |
|---|---|---|---|---|
| `MINERU_API_TOKEN` | **是** | — | string | Bearer Token，从 mineru.net 注册后获取；缺失直接抛 `KeyError` |
| `MINERU_BASE_URL` | 否 | `https://mineru.net/api/v4` | string | API 端点；不含尾部 `/` |
| `MINERU_LANGUAGE` | 否 | `ch` | string | 文档主要语言；影响 OCR 精度（`ch`/`en`/`cht` 等） |
| `MINERU_OCR_ENABLE` | 否 | `true` | string | 是否启用 OCR；multipart 以字符串传递，取值 `"true"`/`"false"` |
| `MINERU_ENABLE_TABLE` | 否 | `true` | string | 是否识别并导出表格 |
| `MINERU_ENABLE_FORMULA` | 否 | `false` | string | 是否识别数学公式（输出 LaTeX） |
| `POLL_INTERVAL` | 否 | `3` | int | 轮询间隔（秒）；建议值 `3–10` |
| `POLL_TIMEOUT` | 否 | `300` | int | 最大等待时长（秒）；大文件建议调大至 `600` |

### 2.2 API 请求参数（multipart/form-data）

`submit_task()` 实际发送字段（基于源码 `mineru_pipeline.py:36-41`）：

| 字段名 | 实际取值来源 | 类型 | 说明 |
|---|---|---|---|
| `file` | 本地 PDF 文件 | binary | multipart 文件体；MIME 类型固定为 `application/pdf` |
| `is_ocr_enable` | `MINERU_OCR_ENABLE` | string | **注意**：源码使用旧参数名 `is_ocr_enable`（规范 v1.0 已更正为 `is_ocr`，但 MVP 代码尚未同步） |
| `enable_table` | `MINERU_ENABLE_TABLE` | string | 字符串 `"true"`/`"false"` |
| `enable_formula` | `MINERU_ENABLE_FORMULA` | string | 字符串 `"true"`/`"false"` |
| `language` | `MINERU_LANGUAGE` | string | 语言代码，如 `"ch"` |

> ⚠️ **参数名勘误**：`mineru_cloud_api_io_spec_v1.0.md` 已将参数名更正为 `is_ocr`，
> 但 `mineru_mvp/mineru_pipeline.py` 源码（第 37 行）仍使用旧名 `is_ocr_enable`。
> Bridge Pipeline 集成测试前需确认 API 实际接受哪个参数名。

### 2.3 MinerU 输出核心参数（`content_list.json`）

顶层结构：**JSON 数组**，每元素为一个 ContentBlock。

**ContentBlock 公共字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | string | 块类型（枚举见下表） |
| `content` | string | 文本内容（Markdown 格式）；`type=image` 时为空字符串 |
| `page_idx` | integer | 所在页码，**0-indexed** |
| `bbox` | `[x0,y0,x1,y1]` | 归一化坐标（0–1000），左上角原点 |

**type 枚举与附加字段：**

| type 值 | content 格式 | 附加字段 | Bridge 处理方式 |
|---|---|---|---|
| `text` | Markdown 字符串 | `text_level`（0=正文,1=H1,2=H2,3=H3） | 保留标题层级，拼接文本 |
| `table` | HTML `<table>` 或 Markdown 表格 | `table_caption`, `table_footnote` | 转 Markdown，标题前置 |
| `list` | Markdown 列表 | — | 直接追加 |
| `code` | 原始代码 | — | 直接追加 |
| `image` | 空字符串 | `img_path`, `img_caption` | **跳过**（无文本） |
| `equation` | LaTeX（无分隔符） | — | **跳过**（对 LLM 提取无意义） |
| `interline_equation` | LaTeX（无分隔符） | — | **跳过** |

**轮询状态枚举（`state` 字段）：**

| 值 | 含义 |
|---|---|
| `pending` | 已入队，等待处理 |
| `running` | 解析进行中 |
| `done` | 完成，`result` 包含 CDN 下载链接 |
| `failed` | 失败，`err_msg` 包含原因 |

---

## 三、LangExtract Pipeline 关键参数规范

### 3.1 模型初始化参数（`OpenAILanguageModel`）

基于 `langextract/mvp_test_deepseek.py` 实际调用：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `model_id` | string | 是 | 模型标识符，如 `"deepseek-chat"` |
| `api_key` | string | **是** | API Key；**必须显式传入，不可省略**（源码 `openai.py:159` 在 `None` 时直接抛 `InferenceConfigError`） |
| `base_url` | string | 否 | 自定义端点；省略则指向 OpenAI 官方地址；DeepSeek 须填 `"https://api.deepseek.com/v1"` |
| `temperature` | float | 否 | 采样温度；建议 `0.0` 确保提取结果稳定 |
| `max_workers` | int | 否 | 并发请求数；默认 `10` |

### 3.2 `lx.extract()` 调用参数

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `text_or_documents` | `str \| Iterable[Document]` | — | **必填**；Bridge 层输出的 `List[Document]` 或纯字符串 |
| `prompt_description` | string | — | **必填**；自然语言抽取指令 |
| `examples` | `list[ExampleData]` | `[]` | 少样本示例；直接影响提取质量，强烈建议提供 |
| `model` | `BaseLanguageModel` | `None` | 预构建模型实例（最高优先级，推荐方式） |
| `max_char_buffer` | int | `1000` | 单块最大字符数；实测推荐值 `2000` |
| `context_window_chars` | `int \| None` | `None` | 跨块携带上文字符数；中文文档建议 `200–400` |
| `extraction_passes` | int | `1` | 顺序重跑次数；`>1` 多次合并提升召回但成倍增加 API 调用 |
| `batch_length` | int | `10` | 每批并发 chunk 数 |
| `max_workers` | int | `10` | 最大并发 worker 数 |

### 3.3 LangExtract 输出格式（基于 `deepseek_result.jsonl` 实际输出）

每行一个 JSON 对象，**顶层字段顺序固定**：`extractions` → `text` → `document_id`

**顶层字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `extractions` | array | 提取结果列表，**第一个顶层字段** |
| `text` | string | 原始输入文本，**第二个顶层字段** |
| `document_id` | string | 文档 ID；格式 `"doc_{8位十六进制}"`，如 `"doc_c0248950"`，**第三个顶层字段** |

**Extraction 对象字段（以实际输出为准）：**

| 字段 | 类型 | 实际示例 | 说明 |
|---|---|---|---|
| `extraction_class` | string | `"公司"` / `"高管"` / `"财务指标"` | 实体分类标签 |
| `extraction_text` | string | `"苹果公司（Apple Inc.）"` | 提取的原文片段；必须与 `text` 完全一致 |
| `char_interval` | `object \| null` | `{"start_pos": 11, "end_pos": 27}` | 字符偏移；`null` 表示无法定位 |
| `alignment_status` | `string \| null` | `"match_exact"` 或 `null` | 对齐状态 |
| `extraction_index` | integer | `1`, `2`, `3`… | 文档内顺序编号，**从 1 开始** |
| `group_index` | integer | `0`, `1`, `2`… | 分组编号，**从 0 开始** |
| `description` | `string \| null` | `null` | 可选描述，通常为 `null` |
| `attributes` | `object \| null` | `{"职位": "CEO", "所属公司": "英伟达"}` | 附加属性键值对 |

**`alignment_status` 枚举值：**

| 值 | 含义 |
|---|---|
| `"match_exact"` | 与原文完全匹配（最高可信） |
| `"match_greater"` | 匹配范围比提取文本更宽 |
| `"match_lesser"` | 匹配范围比提取文本更窄 |
| `"match_fuzzy"` | 模糊匹配 |
| `null` | 无法定位，`char_interval` 同为 `null`（不可信，建议过滤） |

> ⚠️ **实测注意**：中英混排人名（蒂姆·库克、桑达尔·皮查伊等）定位率为 0%（DeepSeek 对人名有轻微规范化），
> 知识图谱构图时应以 `extraction_text` 为节点 ID，不依赖 `char_interval`。

---

## 四、组件对接规范（MinerU → Bridge → LangExtract）

### 4.1 数据流转格式对照

| 阶段 | 输入 | 输出 | 传输方式 |
|---|---|---|---|
| MinerU Pipeline | 本地 PDF 文件路径 | `content_list.json`（JSON 数组） | 本地文件写入 |
| Bridge Layer | `content_list.json` 路径 | `List[lx.data.Document]` | Python 对象，内存传递 |
| LangExtract Pipeline | `List[lx.data.Document]` | `List[AnnotatedDocument]` | Python 对象，内存传递 |
| Graph Builder | `List[AnnotatedDocument]` | `knowledge_graph.json` | 本地文件写入 |

> **无共享 Python 环境要求**：MinerU 输出到文件后，Bridge 层读取文件，
> 两个组件通过文件路径解耦，各自在独立虚拟环境中运行。

### 4.2 Bridge 层处理逻辑（`mineru_to_text.py`）

**核心接口：**

```python
def content_list_to_documents(
    content_list_path: str,       # content_list.json 绝对路径
    pdf_stem: str,                # PDF 文件名（无扩展名），用于构造 document_id
    split_by: str = "page",       # "page"（按页）| "section"（按 H1 标题）| "full"（整文档）
    include_tables: bool = True,  # 是否包含表格内容
    skip_types: set | None = None, # 默认跳过 {"image", "equation", "interline_equation"}
) -> list                         # List[lx.data.Document]
```

**块过滤与文本拼接规则：**

```
content_list.json（数组）
  │
  ├── type=text, text_level=1  →  "# 标题文字\n\n"
  ├── type=text, text_level=2  →  "## 标题文字\n\n"
  ├── type=text, text_level=3  →  "### 标题文字\n\n"
  ├── type=text, text_level=0  →  "正文段落\n\n"
  ├── type=table               →  "[表格标题]\n| 列1 | 列2 |\n|---|---|\n| ... |\n\n"
  ├── type=list                →  "- 列表项\n\n"
  ├── type=code                →  "代码内容\n\n"
  ├── type=image               →  ★ 跳过（content 为空字符串）
  ├── type=equation            →  ★ 跳过（LaTeX 对 LLM 提取无意义）
  └── type=interline_equation  →  ★ 跳过
```

**Document 构造规则（split_by="page"，推荐）：**

```python
# 按 page_idx 分组，每页生成一个 Document
lx.data.Document(
    id=f"doc_{pdf_stem}_p{page_idx}",  # 溯源至原始页码
    text="\n".join(page_text_blocks),  # 该页所有有效块的拼接文本
)
```

**HTML 表格转 Markdown 规则：**

```python
def html_table_to_md(html_content: str, caption: str = "") -> str:
    # 解析 <table><tr><th>/<td> 结构
    # 输出格式：
    #   {caption}\n          ← 表格标题（若有）
    #   | col1 | col2 | ...\n
    #   |---|---|...\n
    #   | val1 | val2 | ...\n
```

### 4.3 Bridge 层输出 → LangExtract 输入规范

Bridge 层输出的 `List[lx.data.Document]` 直接传入 `lx.extract()` 的 `text_or_documents` 参数：

```python
# langextract_kg.py 调用示例
documents = mineru_to_text.content_list_to_documents(
    content_list_path="mineru_mvp/results/{task_id[:8]}/content_list.json",
    pdf_stem="my_document",
    split_by="page",
)

result_list = lx.extract(
    text_or_documents=documents,   # List[Document] 传入
    prompt_description=PROMPT_KG,
    examples=EXAMPLES_KG,
    model=model,
    max_char_buffer=2000,
    context_window_chars=300,      # 中文文档建议设置
)
# 返回 List[AnnotatedDocument]，每个 Document 对应一个结果
```

### 4.4 关键约束

| 约束 | 说明 |
|---|---|
| 文件路径必须为绝对路径或脚本相对路径 | Bridge 层接收 `content_list_path` 应使用 `os.path.abspath()` 处理 |
| 单页文本超过 2000 字符时 | LangExtract 自动分块，`context_window_chars` 保障跨块语义连续 |
| `api_key` 必须显式传入 | 不可依赖环境变量自动读取（LangExtract 源码限制） |
| 不共享 Python 环境 | bridge_pipeline 使用独立 `.venv/`，通过文件路径引用 mineru_mvp 输出 |

---

## 五、BridgePipeline 输出关键参数规范

### 5.1 KG 提取结果（`kg_result.jsonl`）

路径：`bridge_pipeline/output/kg_result.jsonl`

每行一个 JSON 对象，格式与 LangExtract 标准输出一致，字段顺序：`extractions` → `text` → `document_id`

**顶层字段：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `extractions` | array | KG 实体/关系提取列表 |
| `text` | string | 该 Document 的原始文本（来自 Bridge 层拼接结果） |
| `document_id` | string | 格式 `"doc_{pdf_stem}_p{page_idx}"`，可溯源至原始 PDF 页码 |

**Extraction 字段（KG 专用扩展）：**

| 字段 | 类型 | KG 使用场景 | 说明 |
|---|---|---|---|
| `extraction_class` | string | 节点类型 / 关系标记 | 取值示例：`实体_人物` / `实体_组织` / `实体_概念` / `关系` |
| `extraction_text` | string | 节点标签 / 关系文本 | 必须与 `text` 原文完全一致 |
| `char_interval` | `object\|null` | 溯源定位（可选） | `{"start_pos": int, "end_pos": int}`；`null` 时不影响构图 |
| `alignment_status` | `string\|null` | 定位质量标记 | `"match_exact"` 最优；`null` 时构图仍有效 |
| `extraction_index` | integer | — | 文档内顺序编号，**从 1 开始** |
| `group_index` | integer | — | 分组编号，**从 0 开始** |
| `attributes` | `object\|null` | 节点/边属性 | 实体节点：`{"类型": "人物", "职位": "CEO"}`；关系边：`{"主体": "A", "客体": "B", "关系类型": "合作"}` |

### 5.2 知识图谱文件（`knowledge_graph.json`）

路径：`bridge_pipeline/output/knowledge_graph.json`

标准节点 + 边格式，支持导入 NetworkX / Neo4j / D3.js：

```json
{
  "nodes": [
    {
      "id": "苹果公司（Apple Inc.）",
      "type": "实体_组织",
      "attributes": {"行业": "科技/消费电子"},
      "source_doc": "doc_my_document_p0"
    }
  ],
  "edges": [
    {
      "source": "蒂姆·库克",
      "target": "苹果公司（Apple Inc.）",
      "relation": "隶属",
      "text": "苹果公司（Apple Inc.）CEO蒂姆·库克",
      "source_doc": "doc_my_document_p0"
    }
  ],
  "meta": {
    "source_pdf": "my_document.pdf",
    "total_nodes": 3,
    "total_edges": 5,
    "created_at": "2026-07-31T10:00:00"
  }
}
```

**构图规则：**

| extraction_class 含 `实体_` | → 节点 | `id = extraction_text`，`type = extraction_class`，`attributes` 来自字段 |
|---|---|---|
| `extraction_class = "关系"` | → 边 | `source = attributes["主体"]`，`target = attributes["客体"]`，`relation = attributes["关系类型"]` |

### 5.3 可视化文件（`kg_result.html`）

路径：`bridge_pipeline/output/kg_result.html`

由 `lx.visualize(jsonl_path)` 生成，自包含 HTML，浏览器直接打开可高亮查看原文定位。

---

## 六、快速运行命令

> ⚠️ **强制要求**：所有命令必须在 `bridge_pipeline/.venv` 激活状态下执行。

### 首次环境搭建

```bash
cd bridge_pipeline

# 1. 创建虚拟环境
uv venv .venv

# 2. 激活
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

# 3. 安装依赖（继承 langextract 依赖栈 + Bridge 额外依赖）
uv pip install langextract[openai] python-dotenv
```

### 完整三阶段运行

```bash
# Stage 1：MinerU 解析（在 mineru_mvp/.venv 下执行）
cd ../mineru_mvp && source .venv/bin/activate
python create_sample_pdf.py
python mineru_pipeline.py          # 输出至 results/{task_id[:8]}/content_list.json
deactivate

# Stage 2+3：Bridge + KG 提取（在 bridge_pipeline/.venv 下执行）
cd ../bridge_pipeline && source .venv/bin/activate
python langextract_kg.py \
  --content-list ../mineru_mvp/results/{task_id[:8]}/content_list.json \
  --pdf-stem {your_pdf_name}
```

### 仅运行 Stage 2+3（已有 content_list.json）

```bash
cd bridge_pipeline
source .venv/bin/activate

python langextract_kg.py \
  --content-list /path/to/content_list.json \
  --pdf-stem my_document
```

**注意事项：**

| 场景 | 说明 |
|---|---|
| 提示符无 `(.venv)` | 未激活虚拟环境，禁止运行脚本 |
| `ModuleNotFoundError: langextract` | 先激活 venv，再执行 `uv pip install langextract[openai]` |
| `InferenceConfigError: API key not provided` | 检查 `.env` 是否含 `OPENAI_API_KEY`，并确认 `OpenAILanguageModel` 显式传入 |
| Stage 1 与 Stage 2+3 环境隔离 | 两个组件使用独立 `.venv`，切换时必须 `deactivate` 后重新激活目标环境 |

---

## 七、CLAUDE.md 全文（`bridge_pipeline/CLAUDE.md`）

> 以下内容为 `bridge_pipeline/CLAUDE.md` 的完整规范，已同步创建为独立文件。

```markdown
# BridgePipeline — Claude Code 工作规范

## 环境隔离要求

本组件（bridge_pipeline）是 MinerU → LangExtract → 知识图谱 对接层，
使用独立的 uv 虚拟环境（`.venv/`），与 mineru_mvp、langextract 等组件完全隔离。

**⚠️ 强制要求：执行任何 BridgePipeline 相关操作前，必须先进入本目录并激活虚拟环境。**

​```bash
# 进入本组件目录
cd bridge_pipeline

# 激活虚拟环境（每次新开终端均需执行）
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

# 确认激活成功（提示符前应显示 (.venv)）
which python
# → .../bridge_pipeline/.venv/bin/python
​```

退出虚拟环境：
​```bash
deactivate
​```

## 依赖安装

激活虚拟环境后：

​```bash
uv pip install langextract[openai] python-dotenv
​```

## 运行命令

​```bash
# 完整三阶段：Bridge 转换 + KG 提取
python langextract_kg.py \
  --content-list ../mineru_mvp/results/{task_id[:8]}/content_list.json \
  --pdf-stem {pdf_name}

# 输出目录：bridge_pipeline/output/
#   kg_result.jsonl        ← KG 提取结果（JSONL）
#   kg_result.html         ← 交互式可视化
#   knowledge_graph.json   ← 知识图谱（nodes + edges）
​```

## 目录结构

​```
bridge_pipeline/
├── .venv/                         # uv 虚拟环境（不提交 git，需先激活）
├── CLAUDE.md                      # Claude Code 工作规范（本文件）
├── .env                           # API Key 及模型配置（不提交 git）
├── mineru_to_text.py              # Bridge 层：content_list.json → List[Document]
├── langextract_kg.py              # KG 提取入口（Stage 2 + Stage 3）
├── graph_builder.py               # 知识图谱构建
└── output/                        # 运行时自动创建
    ├── kg_result.jsonl
    ├── kg_result.html
    └── knowledge_graph.json
​```

## 环境配置（`.env`）

| 变量 | 说明 |
|---|---|
| `OPENAI_API_KEY` | DeepSeek / OpenAI API Key |
| `DEEPSEEK_BASE_URL` | 自定义端点（如 `https://api.deepseek.com/v1`） |
| `DEEPSEEK_MODEL` | 模型 ID（如 `deepseek-chat`） |

## 与其他组件的边界

| 组件 | 虚拟环境 | 交互方式 |
|---|---|---|
| mineru_mvp | `mineru_mvp/.venv/` | 输出 `content_list.json`，由本组件读取 |
| **bridge_pipeline**（本目录） | `bridge_pipeline/.venv/` | Bridge + KG 提取，独立隔离 |
| langextract | `langextract/.venv/` | 库依赖，通过 pip install 引入，不共享 venv |

**跨组件数据流**：mineru_mvp 将 `content_list.json` 写入磁盘，
bridge_pipeline 通过 `--content-list` 参数读取文件路径，无需共享 Python 环境。
```

---

## 附录：文件路径速查

| 文件 | 路径 |
|---|---|
| 本规范文档 | `docs/bridgepipeline-spec-v1.0.md` |
| MinerU Pipeline 规范 | `docs/mineru_cloud_api_io_spec_v1.0.md` |
| LangExtract 规范 | `docs/langextract_spec-v1.0.md` |
| MinerU Pipeline 入口 | `mineru_mvp/mineru_pipeline.py` |
| MinerU 解析输出 | `mineru_mvp/results/{task_id[:8]}/content_list.json` |
| MinerU CLAUDE.md | `mineru_mvp/CLAUDE.md` |
| Bridge 层 | `bridge_pipeline/mineru_to_text.py` |
| KG 提取入口 | `bridge_pipeline/langextract_kg.py` |
| BridgePipeline CLAUDE.md | `bridge_pipeline/CLAUDE.md` |
| KG 提取结果 | `bridge_pipeline/output/kg_result.jsonl` |
| 知识图谱 | `bridge_pipeline/output/knowledge_graph.json` |
| LangExtract MVP 验证输出 | `langextract/output/deepseek_result.jsonl` |



