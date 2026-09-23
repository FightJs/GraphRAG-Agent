# PDF 多模态解析完善 · 规范总览 v1.0

> 版本：v1.0（2026-09-10）  
> 阶段：调研与选型；不编写业务代码  
> 本文是 **索引与协调说明**，不替代三份独立 SPEC。实现时按 SPEC 分别开发。

---

## 1. 三份独立规范

| # | 功能 | SPEC 文档 | 独立开发范围 | 建议优先级 |
| --- | --- | --- | --- | --- |
| 1 | 表格 → JSON + LLM 总结 + KG 实体 | [pdf-table-parsing-spec-v1.0.md](./pdf-table-parsing-spec-v1.0.md) | 表格解析、落盘、总结、TABLE 节点 | P0 |
| 2 | 图片 VLM 路由（OCR/描述）+ KG 实体 | [pdf-image-parsing-spec-v1.0.md](./pdf-image-parsing-spec-v1.0.md) | zip 落盘、路由、OCR/VLM、IMAGE 节点 | P0–P1 |
| 3 | 占位符 + Milvus 传统 RAG | [vector-rag-milvus-placeholder-spec-v1.0.md](./vector-rag-milvus-placeholder-spec-v1.0.md) | 占位符分块、Embedding、Milvus、问答 | P1 |

开发时 **只依赖本功能 SPEC + 共享契约**，避免三个实现互相改文件。

---

## 2. 现状与缺口（共享事实）

| 阶段 | 实现 | 缺口 |
| --- | --- | --- |
| parse | MinerU `content_list` 优先 | zip 图片未落盘 |
| markdown | 表内联 MD；图 skip | 无占位符、无独立媒体 id |
| chunk | page/section/full | 无 `media_refs` |
| kg | 文本实体抽取 | 无 TABLE / IMAGE |
| vector | 进度占位 | 无 embedding / 向量库 |

MinerU 已提供：`type=table`（HTML/MD + caption/footnote）、`type=image`（`img_path` + caption 双字段形态）。

---

## 3. 共享契约（三份 SPEC 的交界）

实现前必须对齐；变更需同步三份文档。

### 3.1 稳定 ID

| 类型 | 格式 | 生成方 |
| --- | --- | --- |
| `table_id` | `tbl_{doc8}_{seq4}` | SPEC-TABLE |
| `image_id` | `img_{doc8}_{seq4}` | SPEC-IMAGE |
| `chunk_id` | 建议 `chk_{doc8}_{index:06d}` 或 UUID | SPEC-VECTOR |
| DOCUMENT 节点 | `doc_{doc8}`，`type=DOCUMENT` | 可由任一媒体 SPEC 在首次写 KG 时创建 |

### 3.2 占位符语法（SPEC-VECTOR 定义，媒体 SPEC 提供 id）

```text
{{TABLE:table_id}}
{{IMAGE:image_id}}
```

### 3.3 媒体存储布局

```text
storage/media/{doc_id}/
  tables/{table_id}.json          # schema table-v1
  images/{image_id}.{ext}
  images/{image_id}.meta.json     # schema image-v1
```

### 3.4 KG 类型独占权

- `TABLE` / `IMAGE` **仅流水线写入**；
- 文本 `kg_extraction` 输出中的同名类型 MUST 丢弃或降为 `CONCEPT`；
- 表/图节点必须含 `media_id` 与 `source_ref`。

### 3.5 索引阶段建议映射

| name | 产出 | 负责 SPEC |
| --- | --- | --- |
| `parse` | content_list / zip | 现有 + IMAGE 落盘 |
| `media` | table JSON + image meta | TABLE + IMAGE |
| `markdown` | 含占位符正文 | VECTOR（消费 TABLE/IMAGE id） |
| `chunk` | chunks + `media_refs` | VECTOR |
| `kg` | 文本 + TABLE + IMAGE | 三者汇合 |
| `vector` | Milvus rows | VECTOR |

对外 API 若仍暴露 5 阶段，可将 `media` 并入 `parse`，内部日志仍按上表。

### 3.6 向量后端决策

- **现行：Milvus**（Lite 开发 / Standalone 类生产）；
- 覆盖既有 pgvector 选型文档；业务库可仍用 SQLite，向量最终一致。

---

## 4. 依赖与可并行性

```text
                    ┌── SPEC-TABLE ──────────────┐
MinerU parse ───────┤                            ├── media_id ──► SPEC-VECTOR
                    └── SPEC-IMAGE（依赖 zip 落盘）┘                      │
                                                                         ▼
                                                              占位符 / Milvus / 问答
```

| 组合 | 可否并行 | 说明 |
| --- | --- | --- |
| TABLE ∥ IMAGE | 可 | 仅共享 DOCUMENT 节点与 media 目录约定 |
| VECTOR ∥ 媒体 | 可（接口先行） | VECTOR 先交付纯文本 Milvus 闭环；媒体行/占位符按契约预留 |
| 三者联调 | 均完成后 | 验收见总览 §6 |

---

## 5. 推荐实施批次

| 批次 | 内容 | 对应 SPEC |
| --- | --- | --- |
| B1 | 表格 JSON + 总结 + TABLE 节点 | TABLE |
| B2 | 图片落盘 + 启发式/OCR + IMAGE 节点 | IMAGE |
| B3 | VLM 路由与描述完善 | IMAGE |
| B4 | 占位符 + 分块 + Milvus Lite + semantic QA | VECTOR |
| B5 | 媒体独立向量行 + 展开去重 + 删除/重建 | VECTOR |
| B6 | Standalone、hybrid、评测校准 | VECTOR（P2） |

---

## 6. 端到端验收（联调）

- [ ] 含表含图 PDF：`tables/*.json` 与 `images/*.meta.json` 齐全。
- [ ] 正文出现 `{{TABLE:...}}` / `{{IMAGE:...}}`，且 id 与媒体文件一致。
- [ ] KG 含 DOCUMENT、TABLE、IMAGE 及 HAS_* 边。
- [ ] Milvus 三类 `content_kind` 可召回；跨用户为空。
- [ ] 问答能答表中数值与图中可见内容，并给出 sources。
- [ ] 无 VLM / 无 LLM Key 时可降级完成索引。

---

## 7. 关联既有文档

| 文档 | 关系 |
| --- | --- |
| [mineru_cloud_api_io_spec_v1.0.md](./mineru_cloud_api_io_spec_v1.0.md) | 上游 I/O |
| [semantic-vector-retrieval-spec.md](./semantic-vector-retrieval-spec.md) | 向量接口语义兼容 |
| [vector-db-selection-and-provisioning-spec-v1.0.md](./vector-db-selection-and-provisioning-spec-v1.0.md) | pgvector 历史方案 |
| [vector-rag-data-model-spec-v1.0.md](./vector-rag-data-model-spec-v1.0.md) | 逻辑模型参考 |

---

**状态**：v1.0 总览；详细约束以三份 SPEC 正文为准。
