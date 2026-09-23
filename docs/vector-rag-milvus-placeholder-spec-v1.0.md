# 占位符与 Milvus 向量 RAG 规范 v1.0

> 文档编号：SPEC-VECTOR  
> 版本：v1.0（2026-09-10）  
> 阶段：调研与选型；本阶段不编写业务代码  
> 独立开发范围：**传统 RAG + 占位符 + Milvus**（功能三）  
> 姊妹规范：[表格结构化与图谱化](./pdf-table-parsing-spec-v1.0.md) · [图片智能解析与图谱化](./pdf-image-parsing-spec-v1.0.md) · [总览](./pdf-multimodal-parsing-spec-v1.0.md)  
> 决策覆盖：本文将向量后端定为 **Milvus**，覆盖 [向量数据库选型规范](./vector-db-selection-and-provisioning-spec-v1.0.md) 中的 pgvector 结论（该文档降级为历史备选）。

---

## 1. 目标与非目标

### 1.1 目标

1. 完成**传统向量 RAG**闭环：embedding → **Milvus** 持久化 → 带租户过滤的 Top-K 检索 → 带来源的 LLM 回答；
2. 正文/chunk 中以**占位符**标注表格与图片出处（`{{TABLE:id}}` / `{{IMAGE:id}}`）；
3. 检索与问答时能**还原占位符**，附带 SPEC-TABLE 的表格 JSON/总结与 SPEC-IMAGE 的 OCR/描述。

### 1.2 非目标

| 非目标 | 说明 |
| --- | --- |
| 表格/图片的解析算法本身 | 见 SPEC-TABLE / SPEC-IMAGE；本规范只消费其产物契约 |
| 图像向量 / 多模态 embedding | v1 仅文本向量（含媒体描述文本） |
| 全文检索引擎替换 | 关键词检索可保留 |
| hybrid RRF / reranker | 接口预留，实现可后置 |
| 图谱 N-hop / 社区检测 | 不在本规范 |
| 业务库从 SQLite 迁出 | 不强制；向量与业务最终一致 |

### 1.3 规范性用语

- **MUST** / **SHOULD** / **MAY**。

---

## 2. 现状基线

| 项 | 现状 | 缺口 |
| --- | --- | --- |
| 分块 | `content_list_to_chunks` / `plain_text_to_chunks`；无媒体占位符；表内联、图丢弃 | 无 `media_refs` |
| 向量阶段 | IndexTask Stage4 仅推进进度 | 无 embedding、无向量库 |
| 检索 | `_retrieve_chunks` 关键词计数 | 无语义召回 |
| Embedding Key | OpenRouter 已用于 Key 验证 | 索引/问答未调用 |
| 既有选型 | pgvector | 本阶段改为 **Milvus** |

---

## 3. 总体数据流

```mermaid
flowchart LR
  subgraph 索引
    CL[content_list + media JSON/meta] --> MD[占位符 Markdown]
    MD --> CK[chunks 含 media_refs]
    CK --> TB[table_summary 行]
    CK --> IM[image_text 行]
    TB --> EM[EmbeddingService]
    IM --> EM
    CK --> EM
    EM --> MV[(Milvus doc_chunks)]
    CK --> FS[(chunks/{doc_id}.json 真相源)]
  end
  subgraph 问答
    Q[question] --> QE[Embedding]
    QE --> S[Milvus search owner 过滤]
    S --> EXP[占位符展开/去重]
    FS --> EXP
    EXP --> LLM[LLM 流式回答 + sources]
  end
```

---

## 4. 占位符规范

### 4.1 语法（MUST）

| 媒体 | 正则 | 示例 |
| --- | --- | --- |
| 表格 | `{{TABLE:table_id}}` | `{{TABLE:tbl_a1b2c3d4_0001}}` |
| 图片 | `{{IMAGE:image_id}}` | `{{IMAGE:img_a1b2c3d4_0000}}` |

- `table_id` / `image_id` 必须已在 SPEC-TABLE / SPEC-IMAGE 生成；
- 占位符 **单独成行**（允许行首尾空白）；前后保留空行；
- 同一 id 在全文 MAY 多次出现，通常一次；
- 行级匹配正则：`^\s*\{\{(TABLE|IMAGE):([a-z0-9_]+)\}\}\s*$`
- 允许占位符上一行保留 caption 作为可读提示（非强制）。

示例正文：

```markdown
表1 各组实验结果对比

{{TABLE:tbl_a1b2c3d4_0001}}

如下图所示：

{{IMAGE:img_a1b2c3d4_0000}}
```

### 4.2 Markdown 生成规则

在 content_list 渲染时：

| block 类型 | 行为 |
| --- | --- |
| `table`（媒体增强成功） | 输出 caption 行 + 空行 + `{{TABLE:table_id}}`；**不再内联完整 HTML/大 MD 表** |
| `image`（媒体增强成功） | 输出 caption（若有）+ `{{IMAGE:image_id}}` |
| `table`/`image`（增强失败或 legacy） | 退化：表内联 MD，图 skip；chunk meta 记 `media_mode=degraded\|legacy` |
| 其他 | 沿用现有渲染 |

### 4.3 分块约束（MUST）

1. 分块器 **不得从占位符中间切开**；滑窗边界必须对齐到完整占位符（可前向/后向微调 ≤ 占位符长度）；
2. 每个 chunk 携带 `media_refs`：文本中出现的全部 media_id；
3. chunk 字典扩展见 §5.1。

### 4.4 占位符展开（问答时 MUST）

组装 prompt 前：

1. 读取 chunk 的 `media_refs`；
2. 加载对应 table JSON（caption/summary/表头/关键行）与 image meta（caption/`final_text`/route）；
3. 将占位符替换为紧凑块：

```text
【表格 | 表1 各组实验结果对比 | 第2页 | id=tbl_a1b2c3d4_0001】
摘要：……
表头：指标 | A组 | B组
关键行：准确率 | 91.2% | 88.5%

【图片 | 图1 系统架构图 | 第3页 | id=img_a1b2c3d4_0000】
类型：diagram（VLM描述）
描述：……
```

4. 若同一 `media_id` 已作为独立向量行被召回，MUST **去重**，避免重复占 token；
5. 展开块计入 token 预算，超预算优先保留 summary/`final_text` 截断。

---

## 5. 可检索行模型

### 5.1 逻辑行（`VectorRow`）

| 字段 | 说明 |
| --- | --- |
| `chunk_id` | 主键，稳定 |
| `owner_id` / `kb_id` / `doc_id` / `revision_id` / `index_version` | 租户与版本 |
| `content_kind` | `text_chunk` \| `table_summary` \| `image_text` |
| `media_id` | 媒体行必填；文本行为 `""` |
| `media_refs` | 仅 `text_chunk`：占位符引用列表 |
| `chunk_index` | revision 内序号；媒体行可为 -1 |
| `page_start` | 0-indexed 页；未知 -1 |
| `content` | 用于展示的截断文本（见 §6.3） |
| `content_hash` | sha256(规范化 content) |
| `embedding` | float[D] |

### 5.2 三类行的 content 构成（MUST）

| content_kind | content 构成 |
| --- | --- |
| `text_chunk` | 含占位符的正文（完整；磁盘真相源另有全文） |
| `table_summary` | `caption + summary + 表头行 + 前若干关键行摘要`（来自 table JSON） |
| `image_text` | `caption_raw + final_text`（来自 image meta） |

说明：媒体独立成行是为了「用户直接问表中数值/图中内容」也能语义命中，与占位符互补。

### 5.3 本地真相源

| 内容 | 路径 |
| --- | --- |
| 文本 chunks | `storage/chunks/{doc_id}.json`（扩展 media_refs） |
| 表格 | `storage/media/{doc_id}/tables/{table_id}.json` |
| 图片 | `storage/media/{doc_id}/images/{image_id}.meta.json` |

Milvus **不是唯一真相源**：`content` 仅摘要/截断；命中后 MUST 回读磁盘组装完整上下文。

### 5.4 `chunks/{doc_id}.json` 扩展示例

```json
[
  {
    "text": "…… {{TABLE:tbl_a1b2c3d4_0001}} ……",
    "page_idx": 1,
    "section": "实验结果",
    "chunk_index": 12,
    "media_refs": ["tbl_a1b2c3d4_0001"],
    "content_type": "text",
    "media_mode": "enhanced"
  }
]
```

- 兼容旧字段：无 `media_refs` 时视为 `[]`；
- `normalize_chunks` MUST 补默认值。

---

## 6. Milvus 选型与部署

### 6.1 决策

| 形态 | 结论 | 适用 |
| --- | --- | --- |
| **Milvus Lite**（pymilvus 本地文件） | **开发 / 单机 MVP MUST 可用** | 零运维 |
| **Milvus Standalone**（Docker） | **类生产 / 预发 SHOULD** | 独立服务 |
| Zilliz Cloud | MAY | 托管免运维 |
| pgvector | 本阶段不采用 | 历史方案 |

业务一致性：向量与业务库 **最终一致**；通过索引任务状态机 + 幂等 upsert + 删除补偿，而非跨库事务。

### 6.2 版本基线

- `pymilvus` 2.4+（实施时锁定具体版本）
- Milvus server 2.4+（Standalone）
- 距离：**COSINE**；与 embedding 归一化策略一致

### 6.3 Collection：`doc_chunks`

Collection 名可加环境前缀，如 `dev_doc_chunks`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `chunk_id` | VarChar(64), **PK** | |
| `owner_id` | VarChar(64) | 强制过滤 |
| `kb_id` | VarChar(64) | 无库用 `""` |
| `doc_id` | VarChar(64) | |
| `revision_id` | VarChar(64) | |
| `index_version` | VarChar(32) | 如 `semantic-v1` |
| `embedding_model` | VarChar(128) | |
| `content_kind` | VarChar(32) | 见 §5.1 |
| `media_id` | VarChar(64) | 无则 `""` |
| `media_refs` | JSON 或 VarChar | 文本行引用列表 |
| `chunk_index` | Int64 | 媒体行 -1 |
| `page_start` | Int64 | 未知 -1 |
| `content` | 大文本 | **建议 ≤2000 字符截断** |
| `content_hash` | VarChar(64) | |
| `embedding` | FloatVector(D) | D 由真实响应确认后锁定 |

索引：

- 向量：开发 Lite 可用 FLAT；Standalone 用 HNSW/AUTOINDEX + COSINE；
- 标量过滤由服务端拼装：`owner_id`、`doc_id`、`kb_id`、`revision_id`、`content_kind`。

### 6.4 过滤与多租户（MUST）

```text
filter:
  owner_id == current_user_id
  AND revision_id ∈ ready_active_revisions
  AND (kb_id / doc_id 在授权范围)
  AND content_kind ∈ allowed   # 默认全部三类
metric: COSINE
top_k: 候选默认 10
```

- 客户端 **不得** 传入任意 Milvus filter 表达式；
- 跨用户查询结果必须为空；
- 阈值 cutoff 必须评测校准，禁止未验证硬编码。

---

## 7. Embedding

### 7.1 选型

- Provider：OpenRouter（用户 Key）
- 模型默认：`qwen/qwen3-embedding-8b`（与现网验证配置一致）
- **维度 D MUST 由一次真实响应确认后写入 profile/配置**，禁止按名称猜测

### 7.2 调用约束

| 项 | 约束 |
| --- | --- |
| 批量 | 16–64 |
| 同 revision 模型 | 必须一致 |
| 幂等 | `chunk_id + content_hash + index_version` 可跳过重嵌入 |
| 失败 | 整 revision 不得 `ready`；可重试 |
| 密钥 | vault；日志禁止 Key 与完整向量 |

### 7.3 IndexProfile / Revision

沿用既有语义向量规范的逻辑模型，落地到：

- 配置或轻量表：`index_version`、model、dimension、distance、chunk_strategy；
- 每文档每次完整构建：`revision_id`；同一时间仅一个 `ready` active revision 可查；
- 重建：新 revision 全量写入 → 计数校验 → 切换 → 旧数据删除（v1 建议删以控成本）。

---

## 8. 服务接口边界（逻辑）

```text
EmbeddingService.embed(texts: list[str], owner_id: str) -> list[list[float]]
EmbeddingService.dimension() -> int   # 来自已确认 profile

VectorStore.ensure_collection(profile) -> None
VectorStore.upsert(rows: list[VectorRow]) -> None
VectorStore.search(query_vector, scope: SearchScope, top_k) -> list[RetrievedRow]
VectorStore.delete_doc(doc_id, owner_id) -> None
VectorStore.delete_revision(revision_id) -> None

MarkdownBuilder.render_with_placeholders(content_list, media_map) -> str
Chunker.split(text_or_blocks) -> list[Chunk]   # 不切断占位符
Placeholder.expand(chunk, media_loader, token_budget) -> str
RAGService.retrieve_and_answer(...) -> stream
```

约束：

- `qa_service` / 路由层不得直接写 Milvus 表达式；
- 向量实现可替换（保留接口），但本阶段后端为 Milvus。

---

## 9. 问答集成

### 9.1 检索模式

| retrieval_mode | 行为 |
| --- | --- |
| `semantic` | **本规范必做**：Milvus 向量 |
| `hybrid` | 向量+关键词 RRF；SHOULD 预留，实现可后置 |
| `kg_only` / graph | 保持现有 KG；媒体实体节点一并进入 KG 摘要 |

推荐默认：有向量后用 `semantic` 或 `hybrid`。

### 9.2 回答与 sources（MUST）

- 只依据检索+展开后的上下文作答；不足则明确未找到；
- `sources` 至少含：`doc_id`、`page_idx`（若知）、`chunk_id` 或 `media_id`、`content_kind`、可选 score；
- 流式事件结构沿用现有 SSE，扩展 sources 字段而非另起协议。

### 9.3 媒体命中去重

候选集合合并后：

1. 同一 `media_id` 的 `table_summary`/`image_text` 行与含该 id 的 `text_chunk` 可同时保留，但展开时媒体块只出现一次；
2. 同 `chunk_id` 去重；
3. 按 token 预算截断，优先保留高分且含占位符的 text_chunk。

---

## 10. 配置项

```text
MILVUS_URI=./storage/milvus/dev_milvus.db
MILVUS_TOKEN=
MILVUS_COLLECTION=doc_chunks
EMBEDDING_MODEL=qwen/qwen3-embedding-8b
EMBEDDING_DIM=                 # 首次真实响应后锁定
EMBEDDING_BATCH_SIZE=32
VECTOR_TOP_K=10
VECTOR_MAX_CONTEXT_CHUNKS=8
VECTOR_CONTENT_MAX_CHARS=2000
INDEX_VERSION=semantic-v1
MINERU_CHUNK_MAX_CHARS=1200
MINERU_CHUNK_OVERLAP=150
```

---

## 11. 失败、幂等与删除

| 场景 | 行为 |
| --- | --- |
| Embedding 部分失败 | revision `failed`/可重试；禁止半成品 `ready` |
| Milvus 不可用 | 索引失败可重试；问答降级关键词（若启用）或明确报错 |
| 无媒体产物 | 仅 `text_chunk` 行；占位符不生成 |
| 删除文档 | 删 Milvus 中 `doc_id` 过滤行 + 磁盘 chunks/media；补偿任务防复活 |
| 重建 | 新 revision → 切换 → 删旧 |

幂等键：`chunk_id`；内容变更 = 新 revision 或同 revision 覆盖 + hash 更新。

---

## 12. 安全

- 连接串与 token 仅环境变量/密钥服务；
- 强制 `owner_id` 过滤；
- 日志不输出向量全文、用户原文超长片段、Key。

---

## 13. 验收标准

- [ ] 正文 Markdown/chunk 中表格图片以 `{{TABLE:...}}` / `{{IMAGE:...}}` 出现，分块不切断占位符。
- [ ] Milvus 中 `text_chunk` / `table_summary` / `image_text` 均可按 `owner_id` 过滤召回。
- [ ] `semantic` 模式：同义改写问题能召回表格/图片证据；`sources` 含 page 与 media/chunk id。
- [ ] 占位符在 prompt 中被展开为 caption+summary/描述，且与独立媒体行去重。
- [ ] 跨用户检索为空；删除文档后 Milvus 无残留。
- [ ] 重建不产生重复 `chunk_id`；维度与 profile 一致。
- [ ] 无媒体文档：RAG 仍可用。

---

## 14. 实施顺序（本规范独立交付）

1. 占位符渲染 + 不切断分块 + `media_refs`（可先兼容无媒体）
2. EmbeddingService + 真实维度探测与 profile
3. Milvus Lite：collection、upsert、search、delete
4. `semantic` 问答替换关键词，sources 扩展
5. 媒体独立向量行写入 + 占位符展开去重
6. revision 切换与删除补偿；（P2）Standalone、hybrid

> 若 SPEC-TABLE / SPEC-IMAGE 尚未完成：本规范可先交付「纯文本 text_chunk + Milvus」，媒体行与占位符接口以空实现/兼容模式对齐，不阻塞向量闭环。

---

## 15. 待确认项

| # | 问题 |
| --- | --- |
| 1 | Embedding 真实维度与最大输入长度 |
| 2 | 业务库是否同步迁出 SQLite |
| 3 | Milvus 部署形态（Lite 仅开发 vs 一律 Standalone） |
| 4 | 评测集与 Recall@5 / P95 阈值责任人 |
| 5 | hybrid RRF 是否纳入本阶段 |

---

## 16. 与既有规范关系

| 文档 | 关系 |
| --- | --- |
| `vector-db-selection-and-provisioning-spec-v1.0.md` | pgvector 结论被本规范 **覆盖**；接口与租户原则仍可参考 |
| `vector-rag-data-model-spec-v1.0.md` | 逻辑模型大体沿用；物理落点从 PG 表改为 Milvus collection + 磁盘真相源 |
| `semantic-vector-retrieval-spec.md` | EmbeddingService / VectorStore / revision 语义兼容；后端实现换 Milvus |

---

## 17. 参考

- pymilvus 文档：Lite / Standalone、Filter、AUTOINDEX
- [表格规范](./pdf-table-parsing-spec-v1.0.md) · [图片规范](./pdf-image-parsing-spec-v1.0.md)
- [总览](./pdf-multimodal-parsing-spec-v1.0.md)
