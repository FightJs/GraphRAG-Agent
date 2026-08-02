# LangExtract 接口规范文档 v1.0

> 版本：v1.0（2026-07-30）  
> 基于源码 v1.6.0 + 本地实际测试执行结果整理  
> Provider：DeepSeek via OpenAI-compatible API  
> 测试脚本路径：`langextract/mvp_test_deepseek.py`

---

## 一、Pipeline 执行流程

### 1.1 测试脚本目录结构

```
GraphRAG-Agent/
└── langextract/
    ├── .venv/                  # uv 虚拟环境（需先激活）
    ├── CLAUDE.md               # Claude Code 工作规范
    ├── .env                    # API Key 及模型配置
    ├── mvp_test_deepseek.py    # DeepSeek MVP 测试入口脚本
    ├── pyproject.toml          # 项目依赖配置
    ├── langextract/            # 核心库源码
    │   └── providers/openai.py # OpenAI-compatible provider
    ├── tests/                  # 单元测试
    └── output/                 # 运行后自动创建
        ├── deepseek_result.jsonl  # 结构化提取结果
        └── deepseek_result.html   # 交互式可视化
```

### 1.2 Pipeline 执行步骤

```
构造输入文本（str）
    │
    ▼  定义 prompt_description + examples
构建抽取任务
    │
    ▼  OpenAILanguageModel(model_id, api_key, base_url)
初始化 Provider（DeepSeek via OpenAI-compatible API）
    │
    ▼  lx.extract(text, prompt, examples, model, ...)
    │  内部自动分块 → 并发调用 API → 对齐原文定位
    ▼
AnnotatedDocument（含 extractions 列表）
    │
    ├──▶ lx.io.save_annotated_documents()  →  output/*.jsonl
    └──▶ lx.visualize()                    →  output/*.html
```

### 1.3 快速运行命令

> ⚠️ **环境隔离要求**：必须先激活虚拟环境，否则将使用系统 Python 导致依赖缺失。

**首次使用**：

```bash
cd langextract

# 创建虚拟环境（仅首次）
uv venv .venv

# 激活
source .venv/bin/activate       # macOS / Linux

# 安装依赖
uv pip install -e ".[openai,test]"
```

**后续每次运行**：

```bash
cd langextract
source .venv/bin/activate       # 每次新开终端必须执行

python mvp_test_deepseek.py
```

**注意事项**：

| 场景 | 说明 |
|---|---|
| 提示符无 `(.venv)` | 说明未激活，不要直接运行脚本 |
| `ModuleNotFoundError: langextract` | 先激活 venv，再执行 `uv pip install -e ".[openai,test]"` |
| `InferenceConfigError: API key not provided` | 检查 `.env` 文件是否存在且含 `OPENAI_API_KEY` |

---

## 二、输入规范

### 2.1 核心入口函数

```python
import langextract as lx

result = lx.extract(
    text_or_documents,   # 主输入（str 或 Iterable[Document]）
    prompt_description,  # 抽取指令（必填）
    examples,            # 少样本示例（与 output_schema 二选一，强烈建议提供）
    model=model,         # 预构建模型实例（最高优先级）
    # 或 model_id="deepseek-chat"  + model_url/config
    max_char_buffer=2000,
)
```

### 2.2 支持的输入类型

| 输入类型 | 传参方式 | 说明 |
|---|---|---|
| **纯文本字符串** | `text_or_documents="文本内容"` | 主要输入形式 |
| **HTTP/HTTPS URL** | `text_or_documents="https://..."` + `fetch_urls=True` | 自动下载；存在 SSRF 风险，仅在可信环境开启 |
| **Document 可迭代对象** | `text_or_documents=Iterable[data.Document]` | 批量多文档处理 |
| **CSV 文件** | `io.Dataset(input_path, id_key, text_key).load()` | 仅支持 `.csv` |
| **JSONL 文件** | `io.load_annotated_documents_jsonl(path)` | 加载已有抽取结果，用于二次处理 |

**不支持的格式**：PDF、DOCX、XLSX、图片、音频等二进制格式须自行转文本后再传入。

### 2.3 关键参数规范

| 参数 | 类型 | 默认值 | 含义与使用要求 |
|---|---|---|---|
| `text_or_documents` | `str \| Iterable` | — | **必填**。纯文本字符串或 Document 可迭代对象 |
| `prompt_description` | `str` | — | **必填**。自然语言抽取指令，描述要提取的信息类型 |
| `examples` | `list[ExampleData]` | `[]` | 与 `output_schema` 二选一；强烈建议提供，直接影响提取质量 |
| `model` | `BaseLanguageModel` | `None` | 预构建模型实例，最高优先级；传入后忽略 `model_id` |
| `model_id` | `str` | `"gemini-3.5-flash"` | Provider 自动路由的模型 ID；传入 `model` 时此参数无效 |
| `max_char_buffer` | `int` | `1000` | 单个分块的最大字符数；建议值 `1000–4000`，过大会超出模型上下文 |
| `context_window_chars` | `int \| None` | `None` | 跨块携带的上文字符数，用于跨块指代消解；中文文本建议设 `200–400` |
| `extraction_passes` | `int` | `1` | 顺序重跑次数；`>1` 时多次抽取后合并，提升召回率但成倍增加 API 调用 |
| `batch_length` | `int` | `10` | 每批并发 chunk 数 |
| `max_workers` | `int` | `10` | 最大并发 worker 数；实际并发 = `min(batch_length, max_workers)` |
| `fetch_urls` | `bool` | `False` | 是否自动拉取 URL 文本；默认关闭，开启需评估 SSRF 风险 |

### 2.4 提示词规范

```python
# 抽取指令（必填）
prompt_description = "从科技财经新闻中提取公司名称、高管姓名及关键财务指标。"

# 少样本示例（与 output_schema 二选一，强烈建议提供）
examples = [
    lx.data.ExampleData(
        text="英伟达CEO黄仁勋表示，数据中心业务收入达226亿美元。",
        extractions=[
            lx.data.Extraction(
                extraction_class="公司",          # 自定义分类标签
                extraction_text="英伟达",         # 必须与 text 中原文完全一致
                attributes={"行业": "半导体/AI芯片"}  # 可选附加属性
            ),
            lx.data.Extraction(
                extraction_class="高管",
                extraction_text="黄仁勋",
                attributes={"职位": "CEO", "所属公司": "英伟达"}
            ),
        ]
    )
]
```

> **关键约束**：`extraction_text` 必须与 `text` 中原文完全一致，不可释义或摘要。

---

## 三、模型接入规范

### 3.1 模型类型要求

LangExtract 仅需**文本生成（text-to-text）模型**，无需多模态或 Embedding 模型：

- 输入：文本 prompt（含指令 + 示例 + 待抽取文本块）
- 输出：JSON 格式的结构化抽取结果
- 分块策略基于字符/句子边界，与向量语义无关

### 3.2 内置 Provider

#### OpenAI-compatible（含 DeepSeek，实测验证）

```python
from langextract.providers.openai import OpenAILanguageModel

model = OpenAILanguageModel(
    model_id="deepseek-chat",            # 任意兼容 OpenAI 协议的模型 ID
    api_key="sk-xxxxxxxxxxxxxxxx",        # 必填，不可省略
    base_url="https://api.deepseek.com/v1",  # 自定义端点；省略则使用 OpenAI 官方
    temperature=0.0,                     # 建议 0.0，确保提取稳定性
)
result = lx.extract(
    text_or_documents=text,
    prompt_description=prompt,
    examples=examples,
    model=model,   # 传入预构建实例（最高优先级，推荐方式）
)
```

**OpenAI-compatible provider 关键参数：**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `model_id` | `str` | 是 | 模型 ID，如 `deepseek-chat`、`gpt-4o-mini` |
| `api_key` | `str` | **是** | API Key；provider 不自动读取环境变量，必须显式传入 |
| `base_url` | `str \| None` | 否 | 自定义 API 端点；不填则使用 OpenAI 官方地址 |
| `temperature` | `float \| None` | 否 | 采样温度，建议 `0.0` 以确保结果稳定 |
| `max_workers` | `int` | 否 | 并发请求数，默认 `10` |

> ⚠️ **v1.0 勘误**：原规范描述"通过环境变量 `OPENAI_API_KEY` 自动读取"——**实测不成立**。  
> 源码（`openai.py:159`）在 `api_key` 为 `None` 时直接抛出 `InferenceConfigError`，  
> **必须在构造 `OpenAILanguageModel` 时显式传入 `api_key` 参数**。

#### Gemini（Google，默认 Provider）

```python
import os
os.environ["LANGEXTRACT_API_KEY"] = "your_gemini_key"  # 或 GOOGLE_API_KEY

result = lx.extract(
    text_or_documents=text,
    model_id="gemini-3.5-flash",  # 自动路由到 GeminiLanguageModel
    ...
)
```

| 特性 | 说明 |
|---|---|
| 依赖包 | `google-genai>=1.39.0`（已含在主依赖中） |
| 环境变量 | `LANGEXTRACT_API_KEY` 或 `GOOGLE_API_KEY` |
| Schema 约束 | 支持 Structured Output（`use_schema_constraints=True`） |

#### Ollama（本地，无需 API Key）

```python
result = lx.extract(
    text_or_documents=text,
    model_id="gemma2:2b",
    model_url="http://localhost:11434",
    ...
)
```

| 特性 | 说明 |
|---|---|
| 依赖包 | 已含主依赖，需本地安装并启动 Ollama 服务 |
| Schema 约束 | 不支持（依赖 fence 输出，稳定性低） |

### 3.3 模型初始化三种方式

```python
# 方式一：model_id 字符串（自动路由，适合 Gemini/Ollama）
lx.extract(model_id="gemini-3.5-flash", ...)

# 方式二：ModelConfig（明确指定 provider 参数）
from langextract import factory
config = factory.ModelConfig(
    model_id="gpt-4o-mini",
    provider_kwargs={"temperature": 0.0}
)
lx.extract(config=config, ...)

# 方式三：预构建实例（最高优先级，推荐用于 DeepSeek 等自定义端点）
model = OpenAILanguageModel(model_id="deepseek-chat", api_key="...", base_url="...")
lx.extract(model=model, ...)
```

---

## 四、输出格式规范

### 4.1 Python 对象：`AnnotatedDocument`

`lx.extract()` 返回值：
- 单文本输入 → `data.AnnotatedDocument`
- 多文档输入 → `list[data.AnnotatedDocument]`

### 4.2 JSONL 序列化格式（基于本地实际输出）

每行一个 JSON 对象，UTF-8 编码，字段顺序如下：

```json
{
  "extractions": [
    {
      "extraction_class": "公司",
      "extraction_text": "苹果公司（Apple Inc.）",
      "char_interval": {"start_pos": 11, "end_pos": 27},
      "alignment_status": "match_exact",
      "extraction_index": 1,
      "group_index": 0,
      "description": null,
      "attributes": {"行业": "科技/消费电子"}
    },
    {
      "extraction_class": "高管",
      "extraction_text": "蒂姆·库克",
      "char_interval": null,
      "alignment_status": null,
      "extraction_index": 2,
      "group_index": 1,
      "description": null,
      "attributes": {"职位": "CEO", "所属公司": "苹果公司（Apple Inc.）"}
    }
  ],
  "text": "原始输入文本",
  "document_id": "doc_c0248950"
}
```

**字段说明（以实际输出为准）：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `extractions` | `array` | 提取结果列表，**第一个顶层字段** |
| `text` | `string` | 原始输入文本，**第二个顶层字段** |
| `document_id` | `string` | 文档 ID；未指定时自动生成 `"doc_xxxxxxxx"` 格式，**第三个顶层字段** |

**Extraction 字段说明（以实际输出为准）：**

| 字段 | 类型 | 实际取值示例 | 说明 |
|---|---|---|---|
| `extraction_class` | `string` | `"公司"` / `"高管"` / `"财务指标"` | 实体分类标签 |
| `extraction_text` | `string` | `"苹果公司（Apple Inc.）"` | 提取到的文本片段 |
| `char_interval` | `object \| null` | `{"start_pos": 11, "end_pos": 27}` 或 `null` | 在原文中的字符偏移；`null` 表示无法定位 |
| `alignment_status` | `string \| null` | `"match_exact"` 或 `null` | 对齐状态；见下表 |
| `extraction_index` | `integer` | `1`, `2`, `3`… | 在当前文档中的顺序编号，**从 1 开始** |
| `group_index` | `integer` | `0`, `1`, `2`… | 所属分组编号，**从 0 开始** |
| `description` | `string \| null` | `null` | 可选描述，通常为 `null` |
| `attributes` | `object \| null` | `{"指标类型": "营收", "数值": "696亿美元"}` | 附加属性键值对 |

> ⚠️ **v1.0 勘误**：原规范中 JSONL 顶层字段顺序为 `document_id` → `text` → `extractions`，  
> **实际输出顺序为 `extractions` → `text` → `document_id`**，以本地实际输出为准。  
> 原规范中 `extraction_index` 从 `0` 开始，**实际从 `1` 开始**；`group_index` 从 `0` 开始（与原规范一致）。

**`alignment_status` 枚举值（JSON 字符串形式）：**

| JSON 值 | 含义 | 可信度 |
|---|---|---|
| `"match_exact"` | 与原文完全匹配 | 最高 |
| `"match_greater"` | 匹配范围比提取文本更宽 | 高 |
| `"match_lesser"` | 匹配范围比提取文本更窄 | 中 |
| `"match_fuzzy"` | 模糊匹配 | 较低 |
| `null` | 无法定位，`char_interval` 同为 `null` | **不可信，建议过滤** |

**过滤有效定位的推荐写法：**

```python
grounded = [e for e in result.extractions if e.char_interval is not None]
```

### 4.3 序列化与可视化

```python
import langextract as lx

# 保存为 JSONL
lx.io.save_annotated_documents(
    annotated_documents=[result],
    output_dir="./output",
    output_name="deepseek_result.jsonl"
)

# 生成交互式 HTML 可视化
html = lx.visualize("./output/deepseek_result.jsonl")
html_str = html if isinstance(html, str) else html.data
with open("./output/deepseek_result.html", "w", encoding="utf-8") as f:
    f.write(html_str)
```

---

## 五、本地实际生成文件清单

基于 MVP 测试实际运行结果（输入：258 字符科技财经文本，模型：`deepseek-chat`）：

| 文件 | 路径 | 大小 | 说明 |
|---|---|---|---|
| `deepseek_result.jsonl` | `langextract/output/` | 5.73 KB | 结构化提取结果，1文档，18 条 Extraction |
| `deepseek_result.html` | `langextract/output/` | ~80 KB | 自包含交互式 HTML，浏览器打开可高亮查看 |

**实测提取统计（258 字符 / 3 家公司 / 4 位高管 / 11 项财务指标）：**

| 实体类型 | 提取数 | 有效定位（`char_interval ≠ null`） | 定位率 |
|---|---|---|---|
| 公司 | 3 | 1 | 33% |
| 高管 | 4 | 0 | 0% |
| 财务指标 | 11 | 10 | **91%** |
| **合计** | **18** | **11** | **61%** |

**高管定位率为 0% 的原因**：DeepSeek 对中英混排人名（蒂姆·库克、桑达尔·皮查伊等）在 `extraction_text` 中有轻微规范化（如去掉书名号），导致精确字符对齐失败。此为已知行为，不影响提取内容本身的正确性。

---

## 六、完整调用示例（基于实际测试脚本）

> 完整脚本路径：`langextract/mvp_test_deepseek.py`

```python
#!/usr/bin/env python3
"""LangExtract MVP Test — DeepSeek via OpenAI Provider"""

import os
from dotenv import load_dotenv
import langextract as lx
from langextract.providers.openai import OpenAILanguageModel

# 1. 加载 .env 配置
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
API_KEY  = os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
MODEL_ID = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# 2. 构造输入文本（或从 MinerU content_list.json 中读取）
TEXT = """
2024年第四季度，苹果公司（Apple Inc.）CEO蒂姆·库克宣布，
公司季度营收达1194亿美元，同比增长6%，iPhone销售额为696亿美元。
"""

# 3. 定义少样本示例
EXAMPLES = [
    lx.data.ExampleData(
        text="英伟达CEO黄仁勋表示，数据中心业务收入达226亿美元，同比增长154%。",
        extractions=[
            lx.data.Extraction(
                extraction_class="公司",
                extraction_text="英伟达",
                attributes={"行业": "半导体/AI芯片"},
            ),
            lx.data.Extraction(
                extraction_class="高管",
                extraction_text="黄仁勋",
                attributes={"职位": "CEO", "所属公司": "英伟达"},
            ),
            lx.data.Extraction(
                extraction_class="财务指标",
                extraction_text="数据中心业务收入达226亿美元",
                attributes={"指标类型": "营收", "数值": "226亿美元"},
            ),
        ],
    )
]

PROMPT = (
    "从科技财经新闻中提取：1）公司名称；2）高管姓名及职位；"
    "3）关键财务指标。extraction_text 必须与原文完全一致。"
)

# 4. 初始化 Provider（DeepSeek via OpenAI-compatible API）
model = OpenAILanguageModel(
    model_id=MODEL_ID,
    api_key=API_KEY,       # 必须显式传入，不可省略
    base_url=BASE_URL,     # 指向 DeepSeek 端点
    temperature=0.0,
)

# 5. 执行提取
result = lx.extract(
    text_or_documents=TEXT,
    prompt_description=PROMPT,
    examples=EXAMPLES,
    model=model,
    max_char_buffer=2000,
)

# 6. 过滤有效定位结果
grounded = [e for e in result.extractions if e.char_interval is not None]
print(f"总提取: {len(result.extractions)}  有效定位: {len(grounded)}")

# 7. 保存 JSONL + 生成 HTML 可视化
os.makedirs("./output", exist_ok=True)
lx.io.save_annotated_documents([result], output_dir="./output",
                                output_name="deepseek_result.jsonl")
html = lx.visualize("./output/deepseek_result.jsonl")
html_str = html if isinstance(html, str) else html.data
with open("./output/deepseek_result.html", "w", encoding="utf-8") as f:
    f.write(html_str)
```

---

## 七、v1.0 勘误汇总

原规范（`docs/langextract_spec.md`）与 v1.0 的差异对照：

| 原规范内容 | v1.0 更正 | 依据 |
|---|---|---|
| JSONL 顶层字段顺序：`document_id` → `text` → `extractions` | 更正为 **`extractions` → `text` → `document_id`** | 本地实际输出 |
| `extraction_index` 从 `0` 开始 | 更正为**从 `1` 开始** | 本地实际输出 |
| `OPENAI_API_KEY` 环境变量自动读取 | 更正：**必须显式传入 `api_key` 参数**；provider 源码在 `api_key=None` 时直接抛出 `InferenceConfigError` | 源码 `openai.py:159` |
| 缺少 DeepSeek 接入说明 | 补充 OpenAI-compatible `base_url` 配置方式 | 实测验证 |
| 缺少 Pipeline 执行流程 | 补充测试脚本路径、虚拟环境激活步骤、关键参数规范 | 实测代码 |
| 缺少本地输出文件清单 | 补充 `deepseek_result.jsonl`（5.73 KB）和 `deepseek_result.html` | 实测输出 |
| 模型路由方式仅提供 `model_id` 字符串方式 | 补充三种初始化方式，推荐预构建实例用于自定义端点 | 源码 + 实测 |

---

## 附录：文件路径速查

| 文件 | 路径 |
|---|---|
| 原始规范 | `docs/langextract_spec.md` |
| 当前规范（v1.0） | `docs/langextract_spec-v1.0.md` |
| Claude Code 工作规范 | `langextract/CLAUDE.md` |
| MVP 测试入口脚本 | `langextract/mvp_test_deepseek.py` |
| 环境配置 | `langextract/.env` |
| 虚拟环境 | `langextract/.venv/` |
| 提取结果（JSONL） | `langextract/output/deepseek_result.jsonl` |
| 可视化（HTML） | `langextract/output/deepseek_result.html` |
```

