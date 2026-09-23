# 表格结构化与图谱化规范 v1.0

> 文档编号：SPEC-TABLE  
> 版本：v1.0（2026-09-10）  
> 阶段：调研与选型；本阶段不编写业务代码  
> 独立开发范围：**仅表格**（功能一）  
> 姊妹规范：[图片智能解析与图谱化](./pdf-image-parsing-spec-v1.0.md) · [占位符与 Milvus 向量 RAG](./vector-rag-milvus-placeholder-spec-v1.0.md) · [总览](./pdf-multimodal-parsing-spec-v1.0.md)

---

## 1. 目标与非目标

### 1.1 目标

对 PDF（经 MinerU `content_list`）中的 **表格** 完成：

1. 将表格解析为**结构化 JSON** 并落盘存储；
2. 调用 **LLM 生成表格总结**（可检索、可入图）；
3. 将表格作为 **KG 实体（`type=TABLE`）** 写入知识图谱，并建立关系。

### 1.2 非目标

| 非目标 | 说明 |
| --- | --- |
| 图片解析 / VLM 路由 | 见 SPEC-IMAGE |
| 向量库选型与检索实现 | 见 SPEC-VECTOR；本规范只定义「表格 JSON / summary」作为后续向量行输入的契约 |
| 占位符语法最终落地到 chunk | 语法在 SPEC-VECTOR 定义；本规范只保证产出稳定 `table_id` 供占位符引用 |
| 公式、代码块图谱化 | 不在范围 |
| 跨页大表自动合并 | v1 不做，见 §12 待确认 |
| 前端表格可视化组件 | 只保证 JSON 可渲染 |

### 1.3 规范性用语

- **MUST** / **SHOULD** / **MAY**：同行业惯例；不满足 MUST 即不合规。

---

## 2. 现状基线

| 项 | 现状 | 缺口 |
| --- | --- | --- |
| MinerU 输出 | `type=table`，`content` 为 HTML 或 Markdown；含 `table_caption` / `table_footnote` / `page_idx` / `bbox` | 未结构化存储 |
| `parsing_service` | `_html_table_to_md()` 转 Markdown 内联进正文 | 无独立 JSON 文件；无 `table_id` |
| LLM | `llm_client.chat_complete`（DeepSeek） | 无表格总结调用 |
| KG | `kg_extraction` 仅从 chunk 文本抽实体 | 无 `TABLE` 节点；LLM 可能把标题误标为 TABLE |

---

## 3. 范围边界（输入 / 输出）

### 3.1 输入

- `content_list` 中 `type == "table"` 的 block；
- 可选：同文档 `text` block 的邻近上下文（仅用于总结时消歧，不改变表格数据）。

### 3.2 输出

| 产物 | 路径 / 位置 | 说明 |
| --- | --- | --- |
| 表格 JSON | `storage/media/{doc_id}/tables/{table_id}.json` | 真相源 |
| 摘要索引清单 | 可并入 `storage/media/{doc_id}/manifest.json`（可选） | 便于流水线枚举 |
| KG 节点与边 | `storage/kg/{doc_id}.json` | `type=TABLE` + 关系 |
| Markdown 中的引用点 | 由 SPEC-VECTOR 消费本规范的 `table_id` | 本规范不强制改 chunk 结构 |

### 3.3 跳过策略

以下表格 MAY 不进入 JSON 主路径，但 MUST 记录原因（`skipped_reason`）：

- 解析后 `n_rows == 0` 或全空单元格；
- 明显装饰线框（无 caption 且行列无业务语义，可由规则或 LLM summary 判定 `skip`）。

跳过的表 **不创建** KG TABLE 节点。

---

## 4. 表格 JSON 契约（MUST）

### 4.1 文件与 ID

- 路径：`media/{doc_id}/tables/{table_id}.json`
- `table_id` 格式：`tbl_{doc_id前8位}_{seq4}`，例如 `tbl_a1b2c3d4_0001`
- `seq` 在同一 `doc_id` 内按 `content_list` 出现顺序从 `0000` 起 **确定性递增**（重建索引可复现）

### 4.2 Schema

```json
{
  "schema_version": "table-v1",
  "table_id": "tbl_a1b2c3d4_0001",
  "doc_id": "<uuid>",
  "page_idx": 1,
  "bbox": [60, 200, 540, 450],
  "caption": "表1 各组实验结果对比",
  "footnote": "注：数据来源于2024年实测",
  "source_format": "html",
  "headers": [["指标", "A组", "B组"]],
  "n_header_rows": 1,
  "rows": [
    ["准确率", "91.2%", "88.5%"],
    ["召回率", "87.0%", "90.1%"]
  ],
  "n_rows": 2,
  "n_cols": 3,
  "html_source": "<table>...</table>",
  "md_source": "| 指标 | A组 | B组 |\n| --- | --- | --- |\n| 准确率 | 91.2% | 88.5% |\n| 召回率 | 87.0% | 90.1% |",
  "summary": "本表对比 A/B 两组实验的准确率与召回率；A 组准确率更高（91.2%），B 组召回率更高（90.1%）。",
  "summary_status": "ok",
  "key_entities": ["准确率", "A组", "B组"],
  "parse_meta": {
    "parser": "html_table_parser",
    "merge_cells": false,
    "warnings": [],
    "skipped_reason": null
  },
  "created_at": "2026-09-10T00:00:00Z"
}
```

### 4.3 字段约束

| 字段 | 约束 |
| --- | --- |
| `schema_version` | 固定 `table-v1` |
| `table_id` | 全局稳定；见 §4.1 |
| `headers` | 二维字符串数组；`n_header_rows=0` 时为 `[]` |
| `rows` | 二维字符串数组；空单元格用 `""`，禁止 `null` |
| `n_header_rows` / `n_rows` / `n_cols` | 与实际数组长度一致；`n_cols` 取表头或数据行的最大列数，行长度不足右侧补 `""` |
| `source_format` | `html` \| `markdown` |
| `html_source` / `md_source` | 至少保留一个；均建议保留以便审计 |
| `summary` | LLM 失败可为 `""` |
| `summary_status` | `ok` \| `failed` \| `skipped` |
| `key_entities` | 总结产出的关键词；失败可为 `[]` |
| `bbox` | 来自 content_list；缺失可为 `null` |
| `page_idx` | 0-indexed，与 MinerU 一致 |

### 4.4 单元格规范化（MUST）

1. HTML 实体解码（`&amp;` `&lt;` 等）；
2. 去首尾空白，内部连续空白压成单空格；
3. **不得改写数值、百分号、单位**；
4. `colspan` / `rowspan`：默认 **向右/向下复制填满覆盖区**，并置 `parse_meta.merge_cells=true`。

---

## 5. 解析选型

| 方案 | 结论 | 理由 |
| --- | --- | --- |
| 确定性 HTML/MD 解析器 | **主路径 MUST** | 可重复、低成本、无数值幻觉 |
| LLM 直接转 JSON | 不作为主路径 | 成本高、易改单元格 |
| 解析失败后 LLM 修复 | **SHOULD 兜底** | `parse_meta.parser=llm_repair`；修复后仍校验行列一致性 |

实现边界：

- HTML：基于标准 HTML table 解析（可扩展自现有 `TableParser`）；
- Markdown：按 `|` 拆列；忽略分隔行 `| --- |`；
- 不规则行：截断/补齐到 `n_cols`，写入 `parse_meta.warnings`。

---

## 6. LLM 表格总结契约

### 6.1 触发条件

- **SHOULD 总结**：`n_rows * n_cols >= 4`，或存在非空 `caption`；
- **MAY 跳过**：过小装饰表 → `summary_status=skipped`，`summary=""`；
- **禁止**：对 `skipped_reason` 非空且未进入主路径的表再调 LLM。

### 6.2 输入组装

优先级：

1. `caption`
2. `md_source`（或由 headers+rows 重建 MD）
3. `footnote`

超长表（建议 `n_rows > 80`）MUST 采样：表头 + 前 30 行 + 后 10 行，并在 prompt 中声明「以下为部分行」。

### 6.3 输出 Schema（JSON mode）

```json
{
  "summary": "2-4 句中文：表主题、关键对比/趋势、异常值",
  "key_entities": ["准确率", "A组"],
  "answer_hints": ["适合回答 A/B 组指标对比类问题"]
}
```

### 6.4 调用参数与失败

| 项 | 约束 |
| --- | --- |
| 模型 | 文本 LLM（DeepSeek chat）；**禁止** VLM |
| `temperature` | 0.0–0.2 |
| `max_tokens` | 建议 512（可配置 `TABLE_SUMMARY_MAX_TOKENS`） |
| `response_format` | json_object |
| 失败 | 解析失败/超时/非 JSON → `summary_status=failed`，`summary=""`，`key_entities=[]`；**JSON 文件与骨架 KG 节点仍 MUST 保留** |
| 密钥 | 用户 vault 中已验证 DeepSeek Key；禁止写日志 |

骨架节点 label 回退顺序：`caption` → 表头首行拼接前 30 字 → `table_id`。

---

## 7. KG 实体与关系

### 7.1 DOCUMENT 根节点（前置）

若该文档 KG 尚无 DOCUMENT 节点，索引阶段 MUST 先创建：

```json
{
  "id": "doc_{doc_id前8位}",
  "label": "<original_name>",
  "type": "DOCUMENT",
  "attributes": {"doc_id": "...", "file_format": "PDF"}
}
```

### 7.2 TABLE 节点

```json
{
  "id": "table_1_a1b2c3",
  "label": "表1 各组实验结果对比",
  "type": "TABLE",
  "attributes": {
    "media_id": "tbl_a1b2c3d4_0001",
    "page_idx": 1,
    "n_rows": 2,
    "n_cols": 3,
    "caption": "表1 各组实验结果对比",
    "summary": "……",
    "summary_status": "ok",
    "source_ref": "{{TABLE:tbl_a1b2c3d4_0001}}"
  }
}
```

> `media_id` 与 `table_id` 同值，便于向量侧与占位符统一引用。`source_ref` 语法见 SPEC-VECTOR。

### 7.3 关系（边）

| source | relation | target | 必要性 |
| --- | --- | --- | --- |
| DOCUMENT | `HAS_TABLE` | TABLE | **MUST** |
| TABLE | `MENTIONS` | 文档内既有实体 | SHOULD；仅当能匹配到时 |

`MENTIONS` 对齐来源：`summary` + `key_entities` + 表头/关键单元格；必须能在本文档已抽实体（或本表周边正文实体）集合中匹配，**禁止捏造**新业务实体。

### 7.4 类型独占权（防污染）

- `TABLE` 类型 **仅允许流水线规则写入**；
- `kg_extraction` 文本抽取输出中若出现 `type=TABLE`，实现 MUST **丢弃该节点**或降为 `CONCEPT`；
- 抽取系统提示 SHOULD 显式说明：不要输出 TABLE/IMAGE 类型。

---

## 8. 服务边界（逻辑接口）

```text
TableService.extract_tables(content_list: list) -> list[RawTableBlock]
TableService.parse_table(block) -> TableRecord          # 纯函数，无 IO
TableService.save_table(doc_id, record) -> table_id
TableService.summarize(record, llm_key) -> TableSummary
TableService.attach_to_kg(kg: dict, records: list[TableRecord]) -> dict
```

- 解析 MUST 为纯函数，便于单测；
- IO（落盘、LLM、写 KG）分层，失败可重试 summarize 而不重下 PDF。

---

## 9. 配置项

```text
TABLE_SUMMARY_ENABLED=true
TABLE_SUMMARY_MAX_TOKENS=512
TABLE_SUMMARY_MIN_CELLS=4
TABLE_LLM_REPAIR_ENABLED=true
TABLE_MAX_ROWS_FOR_FULL_PROMPT=80
```

---

## 10. 失败与降级

| 场景 | 行为 |
| --- | --- |
| HTML 解析失败 | 尝试 MD；再尝试 LLM repair；均失败则存 `rows=[]` + `html_source` + `summary_status=failed`，仍建骨架节点 |
| LLM 不可用 / 无 Key | `summary_status=failed`，不阻断整篇索引 |
| 整篇无表格 | 正常完成；不创建 TABLE 节点 |

幂等：同一 `doc_id` 重建时 `table_id` 序列确定性重算；同 `table_id` 覆盖写 JSON。

---

## 11. 安全

- 表格内容进入 LLM 前须用户已配置 DeepSeek Key；
- 日志禁止输出完整 `html_source`/`rows` 超长原文，可记 `table_id`、行列数、hash。

---

## 12. 验收标准

- [ ] 含表 PDF 解析后，每张有效表存在 `tables/{table_id}.json`，行列与 MinerU 源一致（合并单元格策略可解释）。
- [ ] `summary_status=ok` 时，summary 不改写关键数值；人工抽检可通过「表中 X 是多少」。
- [ ] KG 存在 `type=TABLE` 节点及 `DOCUMENT-HAS_TABLE` 边。
- [ ] 文本 KG 抽取不会伪造 TABLE 节点。
- [ ] 无 DeepSeek Key 时，表格 JSON 仍生成，`summary_status=failed`，索引可完成。
- [ ] 重建索引 `table_id` 稳定，无重复节点。

---

## 13. 实施顺序（本规范独立交付）

1. `table_id` 与 JSON schema + 确定性解析器 + 单测（含 colspan/MD/空表）
2. 落盘与 manifest
3. LLM summarize + 失败降级
4. KG 节点/边写入 + 抽取类型隔离
5. 与 IndexTask `media` 阶段对接（可先并入 parse）

---

## 14. 待确认项

| # | 问题 |
| --- | --- |
| 1 | 跨页大表合并策略 |
| 2 | 表头行数自动识别（>1 行表头）的评测样本 |
| 3 | `MENTIONS` 是否需要置信度字段 |
| 4 | 是否导出 CSV 副本便于调试 |

---

## 15. 参考

- [MinerU Cloud API I/O](./mineru_cloud_api_io_spec_v1.0.md) §4.3 content_list
- 项目内 `backend/app/services/parsing_service.py`（现有 HTML→MD）
- [总览：PDF 多模态解析完善](./pdf-multimodal-parsing-spec-v1.0.md)
