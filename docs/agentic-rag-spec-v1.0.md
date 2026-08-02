# Agentic-RAG 技术架构规范文档 v1.0

> 版本：v1.0（2026-08-01）
> 组件角色：GraphRAG 知识图谱问答层
> 上游依赖：BridgePipeline v1.0（MinerU → Bridge → LangExtract）
> 下游输出：KG Q&A 自然语言答复
> MVP 脚本路径：`GraphRAG-Agent/bridge_web_demo/agentic_rag_mvp.py`
> 运行环境：`bridge_pipeline/.venv`（需激活后执行）

---

## 一、总体架构

### 1.1 五阶段完整流程

```
┌──────────────────── 上游（BridgePipeline v1.0）────────────────────────┐
│ Stage 1: MinerU Cloud API                                              │
│   本地 PDF ──multipart──▶ MinerU Cloud ──轮询──▶ content_list.json     │
│                                                                        │
│ Stage 2: Bridge Layer  (bridge_pipeline/mineru_to_text.py)             │
│   content_list.json ──过滤/拼接──▶ List[lx.data.Document]              │
│                                                                        │
│ Stage 3: LangExtract + DeepSeek  (bridge_pipeline 内)                  │
│   List[Document] ──lx.extract()──▶ List[AnnotatedDocument]             │
│                    ──graph_builder──▶ knowledge_graph.json             │
└─────────────────────────────────────────────────────────────────────────┘
                                │
                                ▼  knowledge_graph.json
┌──────────────────── 本层（Agentic-RAG v1.0）───────────────────────────┐
│ Stage 4: KG 序列化上下文                                                │
│   knowledge_graph.json ──_kg_to_context()──▶ 结构化文本上下文           │
│                                                                        │
│ Stage 5: LangChain KG Q&A（DeepSeek via ChatOpenAI）                   │
│   [SystemMessage(KG上下文) + HumanMessage(问题)]                        │
│     ──ChatOpenAI.invoke()──▶ AIMessage ──▶ str 答复                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 目录结构

```
GraphRAG-Agent/
├── bridge_pipeline/                    # Stage 2+3 运行环境
│   ├── .venv/                          # ★ MVP 运行所需虚拟环境
│   ├── mineru_to_text.py               # Stage 2 Bridge Layer
│   ├── graph_builder.py                # KG 构建器
│   └── output/
│       └── d2b8e67e/
│           └── content_list.json       # ★ 简历 PDF 解析输出（已存在）
│
├── bridge_web_demo/                    # ★ Agentic-RAG MVP 组件
│   ├── agentic_rag_mvp.py              # ★ MVP 主脚本（本规范对应实现）
│   └── output/
│       ├── kg_resume.jsonl             # KG 提取结果（JSONL）
│       └── kg_resume.json             # 知识图谱（nodes + edges）
│
└── docs/
    ├── agentic-rag-spec-v1.0.md        # ★ 本文件
    ├── bridgepipeline-spec-v1.0.md     # 上游 Pipeline 规范
    ├── langextract_spec-v1.0.md        # LangExtract 规范
    └── mineru_cloud_api_io_spec_v1.0.md # MinerU API 规范
```

---

## 二、MVP 脚本执行流程详解

### 2.1 脚本路径与运行方式

**实际路径：** `GraphRAG-Agent/bridge_web_demo/agentic_rag_mvp.py`

**运行命令：**

```bash
# 进入项目根目录
cd GraphRAG-Agent

# 激活 bridge_pipeline 虚拟环境（包含 langextract + langchain-openai）
source bridge_pipeline/.venv/bin/activate

# 执行 MVP
python bridge_web_demo/agentic_rag_mvp.py
```

**依赖说明（bridge_pipeline/.venv 中已安装）：**

| 包名 | 版本要求 | 用途 |
|---|---|---|
| `langextract[openai]` | ≥1.6.0 | KG 实体关系抽取 |
| `langchain-openai` | ≥0.3 | ChatOpenAI 接入 DeepSeek |
| `langchain-core` | ≥0.3 | Messages、BaseMessage |
| `openai` | ≥2.51 | HTTP 底层（被上两者依赖） |

### 2.2 各阶段执行逻辑

#### Stage 2：Bridge Layer（`stage2_bridge()`）

```
输入：bridge_pipeline/output/d2b8e67e/content_list.json
        ↓ content_list_to_documents(split_by="page", include_tables=True)
输出：List[lx.data.Document]，每页一个 Document
      document_id 格式：doc_{pdf_stem}_p{page_idx}
```

- 过滤类型：`image`、`equation`、`interline_equation`（跳过）
- 标题块（`text_level=1/2/3`）转换为 `#`/`##`/`###` Markdown 前缀
- HTML 表格调用 `html_table_to_md()` 转为 Markdown 格式
- 实测输出：简历 PDF → 2 个 Document（p0: 2328 chars，p1: 2049 chars）

#### Stage 3：KG 抽取（`stage3_extract_kg()`）

```
输入：List[lx.data.Document]
        ↓ lx.extract(model=OpenAILanguageModel(deepseek-chat), max_char_buffer=2000)
        ↓ 内部自动分块 → 并发调用 DeepSeek API → 对齐原文定位
输出：List[AnnotatedDocument]，写入 bridge_web_demo/output/kg_resume.jsonl
```

- 实体类型：`实体_人物`、`实体_技能`、`实体_项目`、`实体_公司`、`实体_学校`、`实体_职位`
- 关系类型：`extraction_class="关系"`，`attributes` 含 `主体`/`客体`/`关系类型`
- 实测输出：2 个 AnnotatedDocument，212 条 Extraction

#### Stage 4：KG 构建（`stage4_build_kg()`）

```
输入：List[AnnotatedDocument]
        ↓ build_knowledge_graph(pdf_stem=...)
        ↓ extraction_class 含"实体_" → 节点；extraction_class="关系" → 边
输出：knowledge_graph.json（nodes + edges + meta）
```

- 实测输出：83 个节点，113 条关系边

#### Stage 5：KG Q&A（`create_kg_qa()`）

```
输入：knowledge_graph.json + 用户问题（str）
        ↓ _kg_to_context(kg) → 结构化 KG 文本
        ↓ [SystemMessage(KG上下文), HumanMessage(问题)]
        ↓ ChatOpenAI(deepseek-chat).invoke(messages)
输出：AIMessage.content（str）
```

---

## 三、LangChain Agent 接入规范

### 3.1 模型接入配置（DeepSeek via OpenAI-compatible API）

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model       = "deepseek-chat",
    api_key     = "${DEEPSEEK_API_KEY}",
    base_url    = "https://api.deepseek.com/v1",
    temperature = 0,
    max_tokens  = 1024,
)
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `model` | str | 是 | `deepseek-chat`，DeepSeek Chat 模型 |
| `api_key` | str | 是 | 必须显式传入，不读取环境变量 |
| `base_url` | str | 是 | `https://api.deepseek.com/v1`，兼容 OpenAI 接口 |
| `temperature` | float | 否 | 默认 0，知识检索场景不建议 >0.3 |
| `max_tokens` | int | 否 | 控制答复长度，建议 512–2048 |

### 3.2 消息格式规范

KG Q&A 使用双消息结构（LangChain `BaseMessage` 协议）：

```python
from langchain_core.messages import SystemMessage, HumanMessage

messages = [
    SystemMessage(content="[角色定义]\n[KG序列化上下文]"),
    HumanMessage(content="[用户自然语言问题]"),
]
response = llm.invoke(messages)   # → AIMessage
answer: str = response.content    # → 最终字符串答复
```

**SystemMessage 内容模板：**

```
你是一位候选人信息查询助手，基于以下知识图谱回答关于候选人的问题。
仅使用知识图谱中的信息，不要编造内容。

=== 候选人知识图谱 ===

【节点（实体）】
  · [实体_人物] 肖超
  · [实体_技能] Python  属性: {"proficiency": "熟练"}
  · [实体_公司] 某科技公司
  …（每个节点一行）

【关系（边）】
  · 肖超 --[掌握]--> Python  （原文: 熟练掌握Python）
  · 肖超 --[就职于]--> 某科技公司
  …（每条边一行）
```

### 3.3 输入规范

| 输入项 | 数据源 | 类型 | 说明 |
|---|---|---|---|
| `kg` | `bridge_web_demo/output/kg_resume.json` | dict | 包含 `nodes`/`edges`/`meta` 三个顶层字段 |
| `question` | 外部调用方（CLI / Web / Agent） | str | 自然语言问题，UTF-8，无长度硬性约束 |
| SystemMessage 上下文 | `_kg_to_context(kg)` 内部生成 | str | 长度≈节点数×30chars + 边数×50chars |

**`_kg_to_context()` 序列化规则：**

1. 遍历 `kg["nodes"]`，按格式输出：`· [{node_type}] {label}  属性: {attributes_json}`
2. 遍历 `kg["edges"]`，按格式输出：`· {source} --[{relation}]--> {target}  （原文: {text_snippet}）`
3. 节点顺序：实体类型字母序；边顺序：按 `source` 字母序

### 3.4 输出规范

`llm.invoke(messages)` 返回 `langchain_core.messages.AIMessage`：

| 字段路径 | 类型 | 说明 |
|---|---|---|
| `response` | `AIMessage` | LangChain 消息对象 |
| `response.content` | `str` | 最终自然语言答复（主要使用字段） |
| `response.response_metadata` | `dict` | 包含 `model_name`、`finish_reason`、`token_usage` |
| `response.usage_metadata` | `dict` | 包含 `input_tokens`、`output_tokens`、`total_tokens` |

**输出约束：**
- 语言与问题语言保持一致
- 仅引用 KG 中已存在节点/关系，不编造信息
- 长度受 `max_tokens=1024` 控制，约≤800个汉字

---

## 四、上游关键参数整合

### 4.1 MinerU content_list.json 字段规范

来源规范：`docs/mineru_cloud_api_io_spec_v1.0.md`

**content_list.json 结构：**

```json
[
  {
    "type": "text",         // "text"|"table"|"image"|"equation"|"interline_equation"|"code"|"list"
    "content": "段落文本",
    "page_idx": 0,          // 0-indexed 页码
    "bbox": [x0, y0, x1, y1],  // 归一化坐标 0–1000
    "text_level": null      // 标题层级：1=H1, 2=H2, 3=H3, null=正文
  }
]
```

**Bridge Layer 过滤逻辑（`mineru_to_text.py`）：**

| `type` 值 | 默认处理 | `include_tables=True` | `skip_types` 指定时 |
|---|---|---|---|
| `text` | 保留 | 保留 | 可跳过 |
| `table` | 跳过 | 保留（转MD） | 可跳过 |
| `image` | 跳过 | 跳过 | 可跳过 |
| `equation` | 跳过 | 跳过 | 可跳过 |
| `interline_equation` | 跳过 | 跳过 | 可跳过 |

### 4.2 `content_list_to_documents()` 参数规范

```python
docs = content_list_to_documents(
    content_list_path = str(CONTENT_LIST_PATH),  # 必填，JSON文件绝对路径
    pdf_stem          = "肖超-应届生年经验-Agent_开发工程师",  # 必填，用于 document_id 前缀
    split_by          = "page",          # "page"（每页一Doc）| "all"（合并为一Doc）
    include_tables    = True,            # True=表格转MD并保留
    skip_types        = None,            # None=使用默认过滤；传list可额外跳过类型
)
# 返回类型：list[lx.data.Document]
# document_id 格式：doc_{pdf_stem}_p{page_idx}
```

### 4.3 LangExtract 关键参数规范

来源规范：`docs/langextract_spec-v1.0.md`

**`OpenAILanguageModel` 初始化：**

```python
from langextract.providers.openai import OpenAILanguageModel  # 正确路径

lx_model = OpenAILanguageModel(
    model_id    = "deepseek-chat",
    api_key     = "${DEEPSEEK_API_KEY}",  # 必须显式传入
    base_url    = "https://api.deepseek.com/v1",
    temperature = 0.0,
)
```

**`lx.extract()` 参数：**

| 参数 | 类型 | 说明 |
|---|---|---|
| `text_or_documents` | `list[lx.data.Document]` | Bridge Layer 输出 |
| `prompt_description` | `str` | 任务描述提示词（含实体/关系类型说明） |
| `examples` | `list[lx.data.ExampleData]` | few-shot示例，含`text`+`extractions` |
| `model` | `OpenAILanguageModel` | 上方初始化的模型实例 |
| `max_char_buffer` | `int` | 单次处理字符窗口，推荐 1000–3000 |
| `context_window_chars` | `int` | 上下文重叠字符数，推荐 200–400 |

**LangExtract JSONL 输出格式（每行一个AnnotatedDocument）：**

```json
{
  "extractions": [
    {
      "extraction_index": 1,
      "extraction_class": "实体_技能",
      "span_start": 42,
      "span_end": 48,
      "text": "Python",
      "group_index": 0,
      "attributes": {"proficiency": "熟练"}
    }
  ],
  "text": "原始文档文本...",
  "document_id": "doc_肖超-应届生年经验-Agent_开发工程师_p0"
}
```

**字段约束：**
- `extraction_index`：从 **1** 开始计数（非0起）
- `group_index`：从 **0** 开始计数
- `extraction_class="关系"` 时，`attributes` 必含 `主体`/`客体`/`关系类型` 三个键
- `extraction_class` 含 `实体_` 时，被 `graph_builder.py` 识别为节点

### 4.4 KG 知识图谱格式规范

```json
{
  "nodes": [
    {
      "id": "实体_人物_肖超",
      "label": "肖超",
      "type": "实体_人物",
      "attributes": {},
      "source_docs": ["doc_肖超-应届生年经验-Agent_开发工程师_p0"]
    }
  ],
  "edges": [
    {
      "source": "实体_人物_肖超",
      "target": "实体_技能_Python",
      "relation": "掌握",
      "text_snippet": "熟练掌握Python",
      "source_docs": ["doc_肖超-应届生年经验-Agent_开发工程师_p0"]
    }
  ],
  "meta": {
    "total_nodes": 83,
    "total_edges": 113,
    "source_pdf": "肖超-应届生年经验-Agent_开发工程师",
    "created_at": "2026-07-31T12:00:00"
  }
}
```

---

## 五、最终响应格式规范

### 5.1 `qa()` 函数签名

```python
def create_kg_qa(kg: dict) -> Callable[[str], str]:
    """
    工厂函数：绑定 KG 上下文，返回闭包 qa()。
    kg: knowledge_graph.json 解析结果（dict）
    """
    ...

def qa(question: str) -> str:
    """
    单次问答调用。
    question: 用户自然语言问题
    return:   DeepSeek 基于 KG 生成的自然语言答复（str）
    """
    ...
```

### 5.2 响应字段完整规范

`qa(question)` 直接返回 `str`（原始答复文本）。

若调用方需要结构化封装，推荐以下标准响应格式：

```json
{
  "question":      "候选人的工作经验有哪些？",
  "answer":        "肖超曾在...担任Agent开发工程师，负责...",
  "model":         "deepseek-chat",
  "kg_nodes_used": 83,
  "kg_edges_used": 113,
  "source_pdf":    "肖超-应届生年经验-Agent_开发工程师",
  "token_usage": {
    "input_tokens":  1250,
    "output_tokens": 320,
    "total_tokens":  1570
  },
  "finish_reason": "stop"
}
```

### 5.3 字段定义与约束

| 字段 | 类型 | 来源 | 约束 |
|---|---|---|---|
| `question` | str | 调用方传入 | UTF-8，非空 |
| `answer` | str | `AIMessage.content` | UTF-8，非空，长度≤800中文字符（受`max_tokens=1024`限制） |
| `model` | str | `llm.model_name` | 固定为 `"deepseek-chat"` |
| `kg_nodes_used` | int | `kg["meta"]["total_nodes"]` | ≥0，整数 |
| `kg_edges_used` | int | `kg["meta"]["total_edges"]` | ≥0，整数 |
| `source_pdf` | str | `kg["meta"]["source_pdf"]` | PDF 文件名（不含扩展名） |
| `token_usage.input_tokens` | int | `response.usage_metadata["input_tokens"]` | ≥0，整数 |
| `token_usage.output_tokens` | int | `response.usage_metadata["output_tokens"]` | ≥0，整数 |
| `token_usage.total_tokens` | int | `response.usage_metadata["total_tokens"]` | = input + output |
| `finish_reason` | str | `response.response_metadata["finish_reason"]` | `"stop"` \| `"length"` \| `"content_filter"` |

### 5.4 异常情形处理

| 场景 | 行为 | `answer` 内容 |
|---|---|---|
| KG 为空（0节点0边） | 正常调用，上下文为空 | DeepSeek 返回"无相关信息" |
| 问题超出 KG 知识范围 | 正常调用 | DeepSeek 返回"根据简历信息无法回答" |
| DeepSeek API 超时 | `openai.APITimeoutError` 抛出 | 调用方捕获处理 |
| `max_tokens` 截断 | `finish_reason="length"` | `answer` 为截断文本，需调用方检测 |

---

## 六、关键设计决策与约束说明

### 6.1 KG-Only 模式（无 Embedding）

当前 MVP 为 **KG-Only** 架构，不使用向量检索（Embedding）：

- 所有候选人知识全量注入 `SystemMessage`（约 3000–8000 tokens）
- 适合单份简历（KG 节点数 ≤ 200）
- 超出 DeepSeek 上下文限制（128K tokens）时，需切换至向量检索+KG 混合架构

### 6.2 KG 序列化精度与召回限制

已知限制：
- KG 使用"候选人"通用称谓，`实体_人物` 节点名称为 OCR 识别结果
- OCR 噪声可能导致姓名误识别（如 "并冈山大学" → 应为 "井冈山大学"）
- `_kg_to_context()` 按节点/边顺序全量输出，DeepSeek 负责基于自然语言理解定位答案

### 6.3 LangExtract 提示词设计原则

- `prompt_description` 须明确列出所有实体类型（`实体_人物`/`实体_技能`/...）
- 关系类型须在提示词中定义 `主体`/`客体`/`关系类型` 三元组格式
- few-shot `examples` 至少提供1个完整示例（含实体+关系）

---

## 七、规范交叉引用

| 规范文件 | 覆盖范围 | 本文对应章节 |
|---|---|---|
| `bridgepipeline-spec-v1.0.md` | Stage 1–3 完整规范（MinerU→Bridge→LangExtract） | §2.2 Stage2+3 |
| `mineru_cloud_api_io_spec_v1.0.md` | MinerU API 调用格式、content_list.json 字段 | §4.1 |
| `langextract_spec-v1.0.md` | LangExtract API、JSONL 格式、provider 路径 | §4.3 |
| 本文（`agentic-rag-spec-v1.0.md`） | LangChain 接入、KG Q&A 链路、最终响应格式 | §三–§六 |

**版本历史：**

| 版本 | 日期 | 变更内容 |
|---|---|---|
| v1.0 | 2026-08-01 | 初始版本，基于 MVP 实测结果（83节点/113边/212抽取） |
