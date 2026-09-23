# GraphRAG Agent

GraphRAG Agent 是一个面向私有知识库的全栈图谱问答系统。它将文档上传、文本解析、分块、知识图谱抽取、索引任务编排、可视化编辑和问答记录整合在一个受认证保护的工作流中，并为多用户场景提供用户自带 API Key（BYOK）能力。

## 核心能力

- 多格式文档接入：PDF、DOCX、XLSX、PPTX、HTML、TXT、Markdown、CSV。
- 五阶段异步索引编排：解析、Markdown 表示、分块、知识图谱抽取、向量化索引（可取消）。
- 知识图谱构建、可视化浏览和增量编辑；子图按实体命中 + 最多两跳扩展。
- 单文档与知识库范围的流式问答、问答历史与反馈闭环。
- 三种检索模式：KG-Only / RRF Agentic / Auto。
- 多租户数据所有权校验：知识库、文档、任务、问答和 Webhook 均按用户隔离。
- Webhook 回调支持索引成功/失败事件。

## 检索模式

![三种检索模式](docs/retrieval-modes.svg)

| 模式 | 策略 | 适用场景 |
| --- | --- | --- |
| **KG-Only** | 仅图检索：问题命中实体后抽取两跳子图作答 | 问实体关系、结构关联 |
| **RRF Agentic** | 子查询分解 → 向量 / 关键词 / 知识图谱三路召回 → RRF 融合 | 复合问题、要原文细节 |
| **Auto** | 图节点 ≤200 走 KG-Only；>200 自动切 RRF Agentic | 不想手选时的默认 |

说明：

- **KG-Only** 不注入原文片段，回答以图谱节点与关系为依据，无文档来源溯源。
- **RRF Agentic** 先把问题拆成最多 3 个子查询，每个子查询分别做向量召回与关键词召回，再与 KG 子图一起进入 RRF 融合排序，输出可溯源片段。
- **Auto** 只是策略开关，最终实际生效模式会在问答结果里以 `retrieval_mode_used` 回传。
- 旧模式名 `hybrid` / `semantic` 会自动映射到 `agentic`，兼容历史请求。

## 安全架构

系统要求每位用户独立配置并验证三类服务凭据后才开放业务能力：

| 服务 | 用途 | 验证方式 |
| --- | --- | --- |
| DeepSeek | 图谱抽取与问答 | 最小 Chat Completions 请求 |
| MinerU | 文档解析服务 | 最小 PDF 解析任务请求 |
| OpenRouter Embedding | `qwen/qwen3-embedding-8b` 嵌入模型 | Embeddings 请求 |

凭据从浏览器提交到后端后，先经服务端验证，再以 Fernet 认证加密保存至 `user_api_keys`。数据库中不保存明文；状态接口只返回配置状态、验证时间和末四位提示。业务路由使用 `428 Precondition Required` 统一阻断未完成三项验证的用户，设置和认证路由保持可访问。

部署时必须通过密钥管理服务或平台 Secret 注入 `API_KEY_ENCRYPTION_KEY`。不要将它、用户 API Key、SQLite 数据库或 `.env` 文件提交到仓库。已在聊天中暴露过的测试密钥应立即在服务商控制台轮换。

## 技术组成

- FastAPI、Pydantic v2、SQLAlchemy Async ORM、SQLite（可替换为生产数据库连接）。
- `cryptography` Fernet 应用层加密、JWT Bearer 鉴权、HTTP-only Refresh Cookie。
- React 18、TypeScript、Vite、Tailwind CSS、TanStack Query、Zustand、Lucide、D3。
- `httpx` 异步服务适配器，支持 DeepSeek、MinerU 与 OpenRouter。

```mermaid
flowchart LR
  Browser[React client] --> Auth[JWT authentication]
  Auth --> Settings[Credential settings API]
  Settings --> Verify[Provider verification]
  Verify --> Vault[Fernet encrypted user_api_keys]
  Vault --> Gate[Three-provider readiness gate]
  Gate --> GraphRAG[Document, graph and QA workflows]
  GraphRAG --> DeepSeek[User-scoped DeepSeek credential]
```

## 快速开始

要求：Node.js 18+、Python 3.11+、[uv](https://docs.astral.sh/uv/)。

1. 配置后端环境。

```bash
cp backend/.env.example backend/.env
cd backend
uv sync --extra test
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

将生成的值写入 `backend/.env` 的 `API_KEY_ENCRYPTION_KEY`，并设置强随机 `SECRET_KEY`。

2. 启动后端。

```bash
cd backend
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

3. 启动前端。

```bash
cd frontend
npm ci
npm run dev
```

访问 Vite 输出的地址，注册账号后前往“设置 -> API Key”，依次选择 DeepSeek、MinerU、OpenRouter Embedding，粘贴密钥并点击“验证并保存”。三项均成功后系统自动开放。

前后端分域部署时，在前端构建环境设置 `VITE_API_BASE_URL=https://your-api-domain/api`，并在后端设置 `CORS_ORIGINS=https://your-pages-domain`。

## 部署建议

- 使用 PostgreSQL、对象存储和受控持久卷替代本地 SQLite 与本地文件路径。
- 使用云 Secret Manager/KMS 注入 `API_KEY_ENCRYPTION_KEY`、`SECRET_KEY`，并设置定期轮换策略。
- 在反向代理层启用 HTTPS、限制 CORS 到实际前端域名、配置请求体大小和上传扫描。
- 将 API Key 验证、外部 API 超时和失败率接入可观测性平台；日志中禁止记录 Authorization 头、请求体中的密钥或上游响应体。

## 当前边界

向量召回已接入 Milvus Lite（`storage/milvus`）与 OpenRouter Embedding；未配置 Embedding Key 或处于 MOCK 模式时，RRF Agentic 自动退化为「关键词 + KG」两路。子查询分解目前是启发式规则（标点切分 + 关键词短语），尚未接入 LLM 规划器。Agentic 多轮工具调用、索引语义缓存等能力仍在边界之外。

## 验证

```bash
cd backend
uv run --extra test python -m pytest -q

cd ../frontend
npm run build
```
