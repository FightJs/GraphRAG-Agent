# 多模态 RAG 后端服务架构规范 v2.0

> 版本：v2.0（2026-08-01）
> 覆盖范围：v1.0 全量继承 + JWT 账户认证 / 知识库管理 / Webhook / 流式 Q&A / 多文档联合问答 / KG 编辑 / 问答反馈
> 依赖规范：`mineru_cloud_api_io_spec_v1.0.md` · `langextract_spec-v1.0.md` · `agentic-rag-spec-v1.0.md` · `GraphRAG_Agent_PRD_2.0.md`

---

## 一、系统总体架构（v2.0 升级）

### 1.1 架构全景图

```
┌───────────────────────────────────────────────────────────────────────────┐
│                              客户端层                                      │
│              Web Browser / Mobile App / Third-party Client                 │
└────────────────────────────┬──────────────────────────────────────────────┘
                             │ HTTPS REST API / SSE
┌────────────────────────────▼──────────────────────────────────────────────┐
│                          API 网关层（FastAPI）                              │
│  /api/v1/* (兼容)  |  /api/v2/auth  |  /api/v2/kbs  |  /api/v2/qa       │
│                      /api/v2/kg     |  /api/v2/webhooks                   │
│                             JWT Middleware（统一认证）                      │
└────┬─────────────────┬────────────────┬──────────────┬────────────────────┘
     │                 │                │              │
┌────▼────┐  ┌─────────▼──────┐  ┌─────▼──┐  ┌──────▼──────┐
│ 认证服务 │  │ Indexing       │  │ KG服务  │  │ Q&A服务     │
│  Auth   │  │ Pipeline       │  │ +Edit   │  │ +Streaming  │
│ Service │  │ (Celery+Redis) │  │ Service │  │ +Multi-doc  │
└────┬────┘  └─────────┬──────┘  └─────┬──┘  └──────┬──────┘
     │                 │                │              │
     │      ┌──────────▼──────────┐     │              │
     │      │  外部 API 调用       │     │              │
     │      │  MinerU / LangExtract│    │              │
     │      │  DeepSeek Chat      │     │              │
     │      └──────────┬──────────┘     │              │
     │                 │                │              │
┌────▼─────────────────▼────────────────▼──────────────▼────────────────────┐
│                              存储层                                         │
│  ┌──────────┐  ┌────────────┐  ┌───────────┐  ┌────────┐  ┌────────────┐ │
│  │ 文件存储  │  │ Redis/Celery│  │ KG JSON   │  │ 向量库  │  │ 元数据DB   │ │
│  │(Local/S3)│  │ 任务队列    │  │(per doc)  │  │(v2.0)  │  │(SQLite/PG) │ │
│  └──────────┘  └────────────┘  └───────────┘  └────────┘  └────────────┘ │
└────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 API 版本策略

| 版本前缀 | 适用场景 |
|---|---|
| `/api/v1/*` | v1.0 全部端点，**继续兼容，不删除** |
| `/api/v2/*` | v2.0 新增端点（Auth / KB / KG编辑 / 多文档Q&A / Webhook / 反馈）|
| `/api/v1/qa/query?stream=true` | 在 v1 query 端点上新增 `stream` 参数触发 SSE |

---

## 二、通用约定（v2.0）

### 2.1 认证方式（v2.0 升级为 JWT）

v1.0 使用静态 API Key，v2.0 改为 JWT 双 Token 机制：

| 场景 | 方式 |
|---|---|
| 登录后请求 | `Authorization: Bearer <access_token>` |
| 刷新 Token | `POST /api/v2/auth/refresh`（需 Refresh Token，存于 httpOnly Cookie） |
| 无认证端点 | `GET /api/v1/health`（健康检查无需认证）|

**Token 规格：**

| 类型 | 有效期 | 存储位置 | 续签方式 |
|---|---|---|---|
| Access Token | 24 小时 | 客户端内存 / localStorage | 到期前5分钟静默调用 Refresh |
| Refresh Token | 7 天 | httpOnly Cookie（SameSite=Strict）| 手动登录重新获取 |

### 2.2 统一响应格式（同 v1.0）

```json
{ "code": 0, "msg": "ok", "data": {}, "trace_id": "uuid-string" }
```

### 2.3 SSE 流式响应格式（v2.0 新增）

当 `stream=true` 时，响应改为 `Content-Type: text/event-stream`：

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no

event: delta
data: {"query_id":"xyz789","content":"肖超的核心技能包括：","finish_reason":null}

event: delta
data: {"query_id":"xyz789","content":"Python（熟练）、LangChain","finish_reason":null}

event: done
data: {"query_id":"xyz789","content":"","finish_reason":"stop","token_usage":{"input_tokens":1250,"output_tokens":320,"total_tokens":1570}}

```

| SSE 事件类型 | 含义 | data 字段 |
|---|---|---|
| `delta` | 增量文本片段 | `content`（字符串）、`finish_reason`（null）|
| `done` | 流式完毕 | `content`（空）、`finish_reason`、`token_usage` |
| `error` | 服务端错误 | `code`、`msg` |

---

## 三、认证接口（/api/v2/auth）

### 3.1 用户注册

```
POST /api/v2/auth/register
Content-Type: application/json
```

**Request Body：**

```json
{
  "username": "xiaochao",
  "email":    "xiaochao@example.com",
  "password": "MyP@ssw0rd!"
}
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `username` | string | 3–32 字符，字母数字下划线，唯一 |
| `email` | string | 有效 email 格式，唯一 |
| `password` | string | 8–64 字符，至少含大小写字母各1位 + 数字1位 |

**Response（HTTP 201）：**

```json
{
  "code": 0,
  "data": {
    "user_id":    "u-uuid-abc",
    "username":   "xiaochao",
    "email":      "xiaochao@example.com",
    "created_at": "2026-08-01T08:00:00Z"
  }
}
```

### 3.2 用户登录

```
POST /api/v2/auth/login
Content-Type: application/json
```

**Request Body：**

```json
{ "email": "xiaochao@example.com", "password": "MyP@ssw0rd!" }
```

**Response（HTTP 200）：**

```json
{
  "code": 0,
  "data": {
    "access_token":  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type":    "Bearer",
    "expires_in":    86400,
    "user": {
      "user_id":  "u-uuid-abc",
      "username": "xiaochao",
      "email":    "xiaochao@example.com"
    }
  }
}
```

Refresh Token 通过 `Set-Cookie: refresh_token=...; HttpOnly; SameSite=Strict; Path=/api/v2/auth/refresh` 设置。

**失败场景：**
- 邮箱不存在 → code 4011，msg "邮箱或密码错误"
- 密码错误 → code 4011，msg "邮箱或密码错误"（不区分具体原因，防枚举）
- 连续错误 5 次 → code 4291，账户锁定 15 分钟

### 3.3 刷新 Access Token

```
POST /api/v2/auth/refresh
Cookie: refresh_token=<refresh_token>
```

**Response（HTTP 200）：**

```json
{
  "code": 0,
  "data": {
    "access_token": "eyJhbGci...(新token)...",
    "token_type":   "Bearer",
    "expires_in":   86400
  }
}
```

Refresh Token 过期 → HTTP 401，code 4012，前端跳转登录页。

### 3.4 退出登录

```
POST /api/v2/auth/logout
Authorization: Bearer <access_token>
```

服务端将当前 Refresh Token 加入撤销名单（黑名单），清除 Cookie。

**Response：** `{ "code": 0, "msg": "已退出登录" }`

---

## 四、知识库管理接口（/api/v2/kbs）

### 4.1 创建知识库

```
POST /api/v2/kbs
Content-Type: application/json
Authorization: Bearer <access_token>
```

**Request Body：**

```json
{
  "name":        "2026届简历库",
  "description": "存放应届生简历文档",
  "color":       "blue"
}
```

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `name` | string | 是 | 1–64 字符，当前用户下唯一 |
| `description` | string | 否 | 最长 256 字符 |
| `color` | string | 否 | `blue`/`purple`/`green`/`orange`/`red`，默认 `blue` |

**Response（HTTP 201）：**

```json
{
  "code": 0,
  "data": {
    "kb_id":       "kb-uuid-001",
    "name":        "2026届简历库",
    "description": "存放应届生简历文档",
    "color":       "blue",
    "owner_id":    "u-uuid-abc",
    "doc_count":   0,
    "created_at":  "2026-08-01T08:00:00Z"
  }
}
```

### 4.2 知识库列表

```
GET /api/v2/kbs?page=1&page_size=20
Authorization: Bearer <access_token>
```

**Response：** 标准分页格式，`items` 中每条为§4.1 响应的知识库对象（含 `doc_count`、`indexed_count`）

### 4.3 获取知识库详情

```
GET /api/v2/kbs/{kb_id}
Authorization: Bearer <access_token>
```

**Response data 额外字段：**

| 字段 | 说明 |
|---|---|
| `doc_count` | 知识库内文档总数 |
| `indexed_count` | 已完成索引的文档数 |
| `total_nodes` | 知识库内所有文档 KG 节点总数 |
| `total_edges` | 知识库内所有文档 KG 边总数 |
| `updated_at` | 最近一次文档更新时间 |

### 4.4 更新知识库

```
PATCH /api/v2/kbs/{kb_id}
Content-Type: application/json
Authorization: Bearer <access_token>
```

**Request Body（部分更新，只传需修改的字段）：**

```json
{ "name": "新名称", "color": "purple" }
```

**Response：** 返回更新后的完整知识库对象。

### 4.5 删除知识库

```
DELETE /api/v2/kbs/{kb_id}
Authorization: Bearer <access_token>
```

**行为：** 删除知识库及其下所有文档、KG 数据。**不可逆。** 需要前端二次确认（输入知识库名称）。

**Response：** `{ "code": 0, "msg": "知识库及全部文档已删除", "data": { "kb_id": "...", "deleted_docs": 12 } }`

---

## 五、文档管理接口（v2.0 扩展）

v2.0 在 v1.0 `/api/v1/documents` 基础上新增知识库归属字段，所有接口路径维持向后兼容。

### 5.1 上传文件（v2.0 扩展）

```
POST /api/v1/documents/upload
Content-Type: multipart/form-data
Authorization: Bearer <access_token>
```

**新增字段：**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `kb_id` | string | 否 | 知识库 ID；不传则归入用户默认未分类库 |

其余字段同 v1.0 §4.1。

### 5.2 批量文档上传（v2.0 新增）

```
POST /api/v2/documents/batch-upload
Content-Type: multipart/form-data
Authorization: Bearer <access_token>
```

**Request（multipart）：**

| 字段 | 说明 |
|---|---|
| `files[]` | 多个文件（最多10个，每个≤200MB）|
| `kb_id` | 目标知识库 ID |

**Response（HTTP 202）：**

```json
{
  "code": 0,
  "data": {
    "uploaded": [
      { "doc_id": "...", "filename": "简历A.pdf", "status": "uploaded" },
      { "doc_id": "...", "filename": "简历B.pdf", "status": "uploaded" }
    ],
    "failed": [
      { "filename": "大文件.pdf", "error": "文件超过200MB限制" }
    ]
  }
}
```

---

## 六、索引构建接口（v2.0 扩展）

v2.0 在 v1.0 `/api/v1/index` 基础上新增批量启动功能。

### 6.1 批量启动索引（v2.0 新增）

```
POST /api/v2/index/batch
Content-Type: application/json
Authorization: Bearer <access_token>
```

**Request Body：**

```json
{
  "doc_ids":       ["d2b8e67e-...", "f3c9f78f-..."],
  "model_version": "pipeline",
  "kg_prompt":     "可选自定义提示词"
}
```

| 字段 | 约束 |
|---|---|
| `doc_ids` | 1–10 个文档 ID，文档须属于当前用户，状态为 `uploaded` 或 `failed`（failed 则重试） |

**Response（HTTP 202）：**

```json
{
  "code": 0,
  "data": {
    "tasks": [
      { "task_id": "...", "doc_id": "d2b8e67e-...", "status": "pending" },
      { "task_id": "...", "doc_id": "f3c9f78f-...", "status": "pending" }
    ],
    "skipped": []
  }
}
```

其余索引接口（查询状态、取消）同 v1.0 §五。

---

## 七、知识图谱接口（v2.0 新增编辑）

v2.0 在 v1.0 `/api/v1/kg` 基础上新增编辑端点，路径升级为 `/api/v2/kg`。

### 7.1 保存 KG 编辑结果（v2.0 新增）

```
PATCH /api/v2/kg/{doc_id}
Content-Type: application/json
Authorization: Bearer <access_token>
```

**行为：** 接受前端提交的 diff 操作列表，幂等写入 KG，更新 meta。

**Request Body：**

```json
{
  "operations": [
    {
      "op":   "add_node",
      "node": { "id": "实体_技能_Rust", "label": "Rust", "type": "实体_技能", "attributes": {} }
    },
    {
      "op":   "add_edge",
      "edge": { "source": "实体_人物_肖超", "target": "实体_技能_Rust", "relation": "学习中" }
    },
    {
      "op":      "update_node",
      "node_id": "实体_技能_Python",
      "patch":   { "attributes": { "level": "熟练" } }
    },
    {
      "op":      "delete_node",
      "node_id": "实体_技能_废弃技能"
    },
    {
      "op":      "delete_edge",
      "edge_id": "edge-uuid-xxx"
    }
  ]
}
```

| operation `op` | 说明 |
|---|---|
| `add_node` | 新增节点，需传完整 `node` 对象 |
| `update_node` | 更新节点属性，需传 `node_id` + `patch` |
| `delete_node` | 删除节点及其所有关联边，需传 `node_id` |
| `add_edge` | 新增边，需传完整 `edge` 对象 |
| `update_edge` | 更新边属性，需传 `edge_id` + `patch` |
| `delete_edge` | 删除边，需传 `edge_id` |

**Response（HTTP 200）：**

```json
{
  "code": 0,
  "data": {
    "doc_id":     "d2b8e67e-...",
    "applied_ops": 4,
    "skipped_ops": 1,
    "meta": {
      "total_nodes": 85,
      "total_edges": 115,
      "last_edited_at": "2026-08-01T09:30:00Z"
    }
  }
}
```

**幂等性保证：** 同一 `node_id`/`edge_id` 的 `add_node`/`add_edge` 若已存在则 skip（计入 `skipped_ops`）。

其余 KG 查询接口同 v1.0 §六（路径 `/api/v1/kg/*` 保持兼容）。

---

## 八、问答接口（v2.0 升级）

### 8.1 单文档流式问答（v2.0 升级）

```
POST /api/v1/qa/query
Content-Type: application/json
Authorization: Bearer <access_token>
```

**Request Body（新增 `stream` 字段）：**

```json
{
  "doc_id":    "d2b8e67e-...",
  "question":  "候选人有哪些核心技能？",
  "stream":    true,
  "options": {
    "retrieval_mode": "auto",
    "max_tokens":     1024,
    "temperature":    0.0
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `stream` | bool | `true`=SSE 流式；`false`（默认）= 同步 JSON（兼容 v1.0）|
| `options.retrieval_mode` | string | `kg_only`（默认）/ `hybrid` / `auto`（节点>200自动切混合）|

**stream=false 响应：** 同 v1.0 §7.1（完全兼容）

**stream=true 响应：** SSE 流，格式见§2.3。最终 `done` 事件包含：

```json
{
  "query_id":      "query-uuid-xyz789",
  "finish_reason": "stop",
  "token_usage":   { "input_tokens": 1250, "output_tokens": 320, "total_tokens": 1570 },
  "retrieval_mode_used": "kg_only",
  "kg_nodes_used": 83,
  "kg_edges_used": 113,
  "sources": []
}
```

### 8.2 多文档联合问答（v2.0 新增）

```
POST /api/v2/qa/kb-query
Content-Type: application/json
Authorization: Bearer <access_token>
```

**Request Body：**

```json
{
  "kb_id":    "kb-uuid-001",
  "doc_ids":  ["d2b8e67e-...", "f3c9f78f-...", "a1b2c3d4-..."],
  "question": "三位候选人中谁的Python经验最丰富？",
  "stream":   true,
  "options": {
    "retrieval_mode": "hybrid",
    "max_tokens":     2048,
    "temperature":    0.0
  }
}
```

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `kb_id` | string | 是 | 当前用户的知识库 ID |
| `doc_ids` | list[string] | 是 | 1–10 个已索引文档 ID，均须属于该知识库 |
| `question` | string | 是 | 非空 |
| `stream` | bool | 否 | 同§8.1 |
| `options.retrieval_mode` | string | 否 | `kg_only`/`hybrid`/`auto` |

**stream=true SSE 响应：** 格式同§2.3，`done` 事件额外字段：

```json
{
  "query_id":       "query-kb-xyz",
  "finish_reason":  "stop",
  "token_usage":    { "input_tokens": 4200, "output_tokens": 680, "total_tokens": 4880 },
  "retrieval_mode_used": "hybrid",
  "sources": [
    { "doc_id": "d2b8e67e-...", "doc_title": "肖超简历", "page": 1, "snippet": "熟练掌握Python..." },
    { "doc_id": "f3c9f78f-...", "doc_title": "张三简历",  "page": 2, "snippet": "3年Python后端..." }
  ]
}
```

**`sources` 字段：** 混合检索模式下返回来源段落（来自向量检索匹配），KG-Only 模式下 `sources=[]`。

---

## 九、问答反馈接口（v2.0 新增）

### 9.1 提交问答评分

```
POST /api/v2/qa/{query_id}/feedback
Content-Type: application/json
Authorization: Bearer <access_token>
```

**Request Body：**

```json
{
  "rating":  "positive",
  "comment": "回答准确，引用了正确的技能节点"
}
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `rating` | string | `positive`（👍）/ `negative`（👎），必填 |
| `comment` | string | 可选补充说明，最长 200 字符 |

**约束：** 同一 `query_id` 只能提交一次（重复提交 → code 4093）

**Response（HTTP 201）：**

```json
{
  "code": 0,
  "data": {
    "feedback_id": "fb-uuid-001",
    "query_id":    "query-uuid-xyz789",
    "rating":      "positive",
    "created_at":  "2026-08-01T08:05:00Z"
  }
}
```

---

## 十、Webhook 接口（v1.1 新增）

### 10.1 创建 Webhook

```
POST /api/v2/webhooks
Content-Type: application/json
Authorization: Bearer <access_token>
```

**Request Body：**

```json
{
  "url":    "https://your-server.com/webhooks/graphrag",
  "events": ["index.completed", "index.failed"],
  "secret": "my-webhook-secret-for-hmac"
}
```

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `url` | string | 是 | 有效 HTTPS URL，接收端需在3秒内响应 HTTP 2xx |
| `events` | list[string] | 是 | 订阅事件类型，可选 `index.completed`/`index.failed` |
| `secret` | string | 否 | 用于 HMAC-SHA256 签名验证，最长 128 字符 |

**Response（HTTP 201）：** 返回 `webhook_id`、`url`、`events`、`created_at`

### 10.2 Webhook 事件 Payload 格式

```json
{
  "event":     "index.completed",
  "timestamp": "2026-08-01T07:05:30Z",
  "data": {
    "doc_id":   "d2b8e67e-...",
    "task_id":  "task-uuid-abc123",
    "doc_title":"肖超-应届生年经验-Agent_开发工程师",
    "kg_nodes": 83,
    "kg_edges": 113
  }
}
```

**签名头（配置了 `secret` 时）：** `X-GraphRAG-Signature: sha256=<hmac_hex>`

**重试策略：** 最多重试3次（间隔 1min / 5min / 15min）；3次全败则标记 `delivery_status=failed`

### 10.3 Webhook 管理接口

| 方法 | 路径 | 功能 |
|---|---|---|
| `GET` | `/api/v2/webhooks` | 列出当前用户所有 Webhook |
| `GET` | `/api/v2/webhooks/{webhook_id}` | 获取指定 Webhook 详情 |
| `PATCH` | `/api/v2/webhooks/{webhook_id}` | 更新 URL / 事件订阅 |
| `DELETE` | `/api/v2/webhooks/{webhook_id}` | 删除 Webhook |
| `GET` | `/api/v2/webhooks/{webhook_id}/deliveries` | 查看最近50次投递记录 |

---

## 十一、数据模型规范（v2.0 扩展）

### 11.1 User 模型（v2.0 新增）

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | UUID string | 主键 |
| `username` | string | 唯一，3–32字符 |
| `email` | string | 唯一，有效邮箱 |
| `password_hash` | string | bcrypt哈希（不对外暴露）|
| `created_at` | ISO 8601 | 注册时间 |
| `last_login_at` | ISO 8601 | 最近登录时间（可null）|

### 11.2 KnowledgeBase 模型（v2.0 新增）

| 字段 | 类型 | 说明 |
|---|---|---|
| `kb_id` | UUID string | 主键 |
| `name` | string | 知识库名称，用户下唯一 |
| `description` | string | 可选描述 |
| `color` | string | 卡片颜色标识 |
| `owner_id` | UUID | 所属用户（外键）|
| `doc_count` | int | 关联文档数（计算值）|
| `created_at` | ISO 8601 | 创建时间 |
| `updated_at` | ISO 8601 | 最近更新时间 |

### 11.3 Document 模型（v2.0 新增字段）

在 v1.0 基础上新增：

| 字段 | 类型 | 说明 |
|---|---|---|
| `owner_id` | UUID | 上传用户 ID |
| `kb_id` | UUID | 所属知识库 ID（可null，默认未分类）|
| `kg_edited_at` | ISO 8601 | KG 最近编辑时间（可null）|

### 11.4 QAFeedback 模型（v2.0 新增）

| 字段 | 类型 | 说明 |
|---|---|---|
| `feedback_id` | UUID | 主键 |
| `query_id` | UUID | 关联问答记录 |
| `user_id` | UUID | 反馈用户 |
| `rating` | string | `positive`/`negative` |
| `comment` | string | 可选补充（可null）|
| `created_at` | ISO 8601 | 提交时间 |

### 11.5 Webhook 模型（v1.1 新增）

| 字段 | 类型 | 说明 |
|---|---|---|
| `webhook_id` | UUID | 主键 |
| `owner_id` | UUID | 所属用户 |
| `url` | string | 回调 URL |
| `events` | list[string] | 订阅事件列表 |
| `secret_hash` | string | secret 的哈希（不对外暴露原文）|
| `is_active` | bool | 是否启用（默认 true）|
| `created_at` | ISO 8601 | 创建时间 |

---

## 十二、错误码规范（v2.0 扩展）

在 v1.0 18 个错误码基础上，v2.0 新增以下错误码：

| HTTP 状态 | `code` | 场景 | `msg` 示例 |
|---|---|---|---|
| 401 | 4012 | Refresh Token 过期或失效 | `登录已过期，请重新登录` |
| 401 | 4013 | Access Token 过期 | `Token已过期，请刷新` |
| 400 | 4006 | 注册信息不符合规范 | `密码需包含大小写字母和数字，最少8位` |
| 409 | 4092 | 邮箱或用户名已被注册 | `该邮箱已被注册` |
| 409 | 4093 | 重复提交反馈 | `该问答已提交过反馈，不可重复` |
| 400 | 4007 | 多文档问答 doc_ids 超出范围 | `最多同时选10份文档参与联合检索` |
| 400 | 4008 | doc_ids 中含未索引或无权限文档 | `doc_id f3c9... 未完成索引或无权限访问` |
| 404 | 4044 | 知识库不存在 | `kb_id kb-uuid-... 不存在` |
| 403 | 4031 | 无权限操作（非拥有者） | `无权限编辑该文档的知识图谱` |
| 422 | 4222 | KG operations 格式非法 | `op 字段值非法，应为 add_node/update_node/delete_node/add_edge/update_edge/delete_edge` |
| 400 | 4009 | Webhook URL 不可达（验证时）| `Webhook URL 验证失败，目标服务器未响应` |

---

## 十三、部署架构建议（v2.0）

### 13.1 v2.0 技术栈新增依赖

```
# v1.0 基础上新增
python-jose[cryptography]>=3.3  # JWT 签发与验证
passlib[bcrypt]>=1.7            # 密码哈希
httpx>=0.27                     # Webhook 异步投递
qdrant-client>=1.9              # 向量数据库（混合检索，v2.0）
langchain-community>=0.3        # 向量检索链
```

### 13.2 开发环境启动（v2.0）

```bash
# 1. 启动 Redis（任务队列）
redis-server

# 2. 启动 Qdrant（向量库，v2.0 混合检索）
docker run -p 6333:6333 qdrant/qdrant

# 3. 启动 Celery Worker
celery -A app.tasks worker --loglevel=info --concurrency=2

# 4. 启动 FastAPI 服务
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 13.3 生产环境目录结构（v2.0）

```
backend/
├── app/
│   ├── main.py
│   ├── routers/
│   │   ├── auth.py           # /api/v2/auth
│   │   ├── kbs.py            # /api/v2/kbs
│   │   ├── documents.py      # /api/v1/documents + /api/v2/documents
│   │   ├── index.py          # /api/v1/index + /api/v2/index/batch
│   │   ├── kg.py             # /api/v1/kg + /api/v2/kg
│   │   ├── qa.py             # /api/v1/qa + /api/v2/qa
│   │   ├── webhooks.py       # /api/v2/webhooks
│   │   └── health.py
│   ├── tasks/
│   │   ├── indexing.py       # Celery 索引 Pipeline
│   │   └── webhook.py        # Celery Webhook 投递任务
│   ├── services/
│   │   ├── auth_service.py   # JWT / 用户管理
│   │   ├── kb_service.py     # 知识库 CRUD
│   │   ├── mineru_service.py
│   │   ├── kg_service.py
│   │   ├── kg_editor.py      # KG 编辑操作处理
│   │   ├── qa_service.py     # 单文档 Q&A
│   │   ├── kb_qa_service.py  # 多文档 Q&A + 混合检索
│   │   └── vector_service.py # Qdrant 向量索引/检索
│   ├── models/               # Pydantic + SQLAlchemy 数据模型
│   ├── middleware/
│   │   └── jwt_middleware.py # JWT 验证中间件
│   └── storage/
├── bridge_pipeline/
├── tests/
└── requirements.txt
```

---

## 十四、规范交叉引用（v2.0）

| 规范文件 | 本文对应章节 |
|---|---|
| `mineru_cloud_api_io_spec_v1.0.md` | §五（文件格式）、§六（索引接口）|
| `langextract_spec-v1.0.md` | §六（KG提取阶段）、§七（KG接口数据格式）|
| `agentic-rag-spec-v1.0.md` | §八（问答接口）|
| `GraphRAG_Agent_PRD_2.0.md` | §三（Auth）、§四（KB）、§八（流式+多文档Q&A）、§九（反馈）、§十（Webhook）|
| `backend-service-api-spec-v1.0.md` | v2.0 完全继承 v1.0 所有接口（`/api/v1/*`）|

**版本历史：**

| 版本 | 日期 | 说明 |
|---|---|---|
| v1.0 | 2026-08-01 | 初始版本，覆盖文档管理/索引/KG/问答完整接口 |
| v2.0 | 2026-08-01 | 新增：JWT认证 / 知识库管理 / KG编辑 / 流式问答 / 多文档Q&A / 问答反馈 / Webhook |
