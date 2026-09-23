# 图片智能解析与图谱化规范 v1.0

> 文档编号：SPEC-IMAGE  
> 版本：v1.0（2026-09-10）  
> 阶段：调研与选型；本阶段不编写业务代码  
> 独立开发范围：**仅图片**（功能二）  
> 姊妹规范：[表格结构化与图谱化](./pdf-table-parsing-spec-v1.0.md) · [占位符与 Milvus 向量 RAG](./vector-rag-milvus-placeholder-spec-v1.0.md) · [总览](./pdf-multimodal-parsing-spec-v1.0.md)

---

## 1. 目标与非目标

### 1.1 目标

对 PDF（经 MinerU zip + `content_list`）中的 **图片** 完成：

1. **资产落盘**：下载 zip 中图片文件并持久化；
2. **VLM 路由**：先判断应走 **OCR** 还是 **VLM 描述**（或 skip）；
3. 按路由执行 OCR / 描述，形成统一解析结果；
4. 将图片作为 **KG 实体（`type=IMAGE`）** 写入知识图谱并建立关系。

### 1.2 非目标

| 非目标 | 说明 |
| --- | --- |
| 表格 JSON / LLM 表总结 | 见 SPEC-TABLE |
| 向量库与占位符分块 | 见 SPEC-VECTOR；本规范只保证稳定 `image_id` 与 `final_text` |
| 图像 embedding / CLIP / 以图搜图 | v1 不做 |
| 人脸/证件脱敏 | 不做主动脱敏；文档提示隐私风险 |
| 非 PDF 格式的深度图片抽取 | v1 以 MinerU PDF 路径为主 |

### 1.3 规范性用语

- **MUST** / **SHOULD** / **MAY**。

---

## 2. 现状基线

| 项 | 现状 | 缺口 |
| --- | --- | --- |
| MinerU `content_list` | `type=image`，字段含 `img_path`、`bbox`、`page_idx` | caption 字段存在 **`img_caption`（字符串）与 `image_caption`（数组）** 两种形态，必须兼容 |
| `mineru_service._fetch_outputs` | 可下载 content_list / markdown；zip 只为取 content_list | **不持久化 `images/**`** |
| `parsing_service` | `_SKIP_BLOCK_TYPES` 含 `image` | 正文直接丢弃图片 |
| `llm_client` | 仅 DeepSeek 文本 chat | **无 VLM**；图片必须走 OpenRouter vision 或降级启发式 |
| KG | 无 IMAGE 节点 | — |

**前置硬依赖**：未实现 zip 图片落盘前，不得宣称图片解析完成。

---

## 3. 范围边界（输入 / 输出）

### 3.1 输入

- `content_list` 中 `type == "image"` 的 block；
- zip 内 `img_path` 指向的图片二进制；
- 可选上下文：同页 text block 摘要、`caption`。

### 3.2 输出

| 产物 | 路径 | 说明 |
| --- | --- | --- |
| 图片文件 | `storage/media/{doc_id}/images/{image_id}.{ext}` | 原图或规范化副本 |
| 解析 meta | `storage/media/{doc_id}/images/{image_id}.meta.json` | 路由 + OCR + 描述 |
| KG 节点与边 | `storage/kg/{doc_id}.json` | `type=IMAGE` + 关系 |
| 占位符引用 id | `image_id` 供 SPEC-VECTOR 使用 | 本规范不实现占位符渲染 |

### 3.3 过滤（不进入 VLM/OCR）

MUST 跳过并记 `status=skipped`：

- 解码失败、0 字节；
- 宽或高 < 32px，或面积 < 1024 px²；
- 纯装饰且路由置信度高（见 §6）。

---

## 4. 图片 ID 与资产落盘

### 4.1 ID

- 格式：`img_{doc_id前8位}_{seq4}`，如 `img_a1b2c3d4_0000`
- `seq` 按 content_list 中 image block 出现顺序从 `0000` **确定性**递增
- 重建索引可复现；与 zip 内 hash 文件名解耦

### 4.2 落盘要求（MUST）

1. 当 `type=image` 且 `img_path` 非空时，MinerU 结果必须尝试下载 `full_zip_url` / `zip_url`；
2. 解压 `images/**` 到内存后，按 content_list 对齐，写入 `media/{doc_id}/images/{image_id}{原扩展名}`；
3. `origin_relpath` 保留 zip 内相对路径便于追溯；
4. 仅 content_list 引用到的图片 MUST 保留；多余文件 MAY 删除；
5. zip 下载失败但已有历史落盘图片时，MAY 复用；否则 image block 记 `status=missing_asset`。

### 4.3 预处理

- 送 VLM 前：最长边缩放到 ≤ `VLM_MAX_IMAGE_SIDE`（建议 1568）；
- OCR 可使用原图或 1.5–2 倍放大图（由引擎决定）；
- 缩放图 MAY 另存 `*_vlm.png`，不覆盖原图。

---

## 5. 统一解析结果契约（meta.json）

```json
{
  "schema_version": "image-v1",
  "image_id": "img_a1b2c3d4_0000",
  "doc_id": "<uuid>",
  "page_idx": 2,
  "bbox": [80, 300, 480, 600],
  "img_path": "media/{doc_id}/images/img_a1b2c3d4_0000.png",
  "origin_relpath": "images/c4df....jpg",
  "caption_raw": "图1 系统架构图",
  "caption_source": "img_caption",
  "route": {
    "decision": "ocr",
    "confidence": 0.86,
    "reason": "画面主体为密集文字截图",
    "image_kind": "screenshot",
    "model": "qwen/qwen2.5-vl-72b-instruct",
    "latency_ms": 1200,
    "fallback": false
  },
  "ocr": {
    "engine": "rapidocr",
    "text": "……",
    "avg_confidence": 0.91,
    "status": "ok"
  },
  "describe": {
    "text": "",
    "status": "skipped"
  },
  "final_text": "……",
  "final_kind": "ocr_text",
  "status": "ok",
  "error": null,
  "created_at": "2026-09-10T00:00:00Z"
}
```

### 5.1 字段约束

| 字段 | 约束 |
| --- | --- |
| `schema_version` | 固定 `image-v1` |
| `caption_raw` | 优先级：`img_caption` 字符串 → `image_caption` 数组 join → `""` |
| `caption_source` | `img_caption` \| `image_caption` \| `empty` |
| `route.decision` | `ocr` \| `describe` \| `skip` |
| `ocr` / `describe` | 结构固定；未执行侧 `status=skipped`，禁止缺字段 |
| `ocr.status` / `describe.status` | `ok` \| `failed` \| `skipped` |
| `final_text` | 对外规范化文本；可为空 |
| `final_kind` | `ocr_text` \| `description` \| `caption_only` \| `empty` |
| `status` | `ok` \| `skipped` \| `failed` \| `missing_asset` |
| `route.fallback` | 是否发生 ocr↔describe 降级补跑 |

### 5.2 `final_text` 组装规则（MUST）

1. 若 `ocr.status=ok` 且 `len(text.strip()) >= MIN_OCR_CHARS`（建议 10）→ `final_text=ocr.text`，`final_kind=ocr_text`；
2. 否则若 `describe.status=ok` 且非空 → 使用描述，`final_kind=description`；
3. 否则若有 `caption_raw` → `final_kind=caption_only`；
4. 否则 `final_text=""`，`final_kind=empty`。

OCR 与 describe 都成功且路由选了 ocr 但 OCR 质量差时：MAY 采用 describe 并保持 `route.decision=ocr`、`route.fallback=true`。

---

## 6. VLM 路由

### 6.1 选型结论

| 方案 | 结论 |
| --- | --- |
| 纯启发式（面积/caption） | 仅无 VLM Key 时的降级 |
| **单次 VLM 分类** | **主路径 MUST** |
| 先 OCR 再 LLM 判断 | 不采用（慢、贵、耦合） |
| 专用分类 CNN | 不引入 |

### 6.2 VLM 供应商边界

- **DeepSeek 不承担 VLM**；
- MUST 使用 OpenRouter 兼容 **vision chat**（用户 OpenRouter Key）；
- 默认模型建议（评测后锁定）：`qwen/qwen2.5-vl-72b-instruct`，成本敏感可降档；
- 路由调用 `max_tokens ≤ 200`，`temperature ≤ 0.2`；
- 图片以 OpenAI 兼容 `image_url`（base64 data URL）传入。

### 6.3 路由输出 Schema

```json
{
  "decision": "ocr|describe|skip",
  "confidence": 0.0,
  "image_kind": "screenshot|chart|diagram|photo|table_image|logo|decorative|mixed|unknown",
  "reason": "一句话"
}
```

### 6.4 决策规则（MUST）

| 条件 | 决策 / 后续 |
| --- | --- |
| `confidence < 0.55`（可配 `MEDIA_ROUTE_MIN_CONFIDENCE`） | 先 OCR；若 OCR 文本过短或低置信，再 VLM 描述；`route.fallback=true` |
| `image_kind ∈ {screenshot, table_image}` | 优先 `ocr` |
| `image_kind ∈ {chart, diagram, photo, mixed}` | 优先 `describe`；描述 prompt MUST 要求复述可见文字与数值 |
| `image_kind ∈ {logo, decorative}` 或尺寸过小 | `skip`，仅 caption |
| VLM 调用失败 | 降级启发式；启发式也失败 → `route.decision=skip` 或仅 caption，`status` 不伪造成 ok |

启发式降级（无 VLM Key 时 MUST 可用）：

- 有 `caption_raw` 且 caption 含「图」「架构」「流程」→ `describe`；
- 否则默认先试 `ocr`，再按 `final_text` 规则回退 caption。

---

## 7. OCR 路径

### 7.1 选型

| 引擎 | 结论 |
| --- | --- |
| **RapidOCR（ONNX）** | **默认采用** |
| PaddleOCR | 备选，文档记录切换原因 |
| Tesseract | 不默认 |
| MinerU 整页 OCR | 不替代单图 OCR |

### 7.2 约束

- `ocr.engine` 记录引擎名与语言包；
- 语言默认 `ch`（可配 `OCR_LANG`）；
- 文本规范化：压缩空行、合并断行；**不得改写数字与专有名词**；
- `avg_confidence < 0.5` 视为低质量：按 §5.2 触发兜底；
- OCR 异常 → `ocr.status=failed`，不抛穿到整篇索引。

---

## 8. VLM 描述路径

### 8.1 输入

- 图片（base64）；
- `caption_raw`；
- 可选：同页 text 前 300 字。

### 8.2 输出要求

- 中文、客观、可检索；
- MUST 包含：可见文字、图表/示意图类型、主要信息或结论；
- 禁止编造图中不存在的数据；
- 长度建议 80–300 汉字（`IMAGE_DESC_MAX_TOKENS` 控制）。

### 8.3 失败

- 超时/非 JSON/空文本 → `describe.status=failed`；
- 回退 caption（§5.2），索引继续。

---

## 9. KG 实体与关系

### 9.1 DOCUMENT 根节点

与 SPEC-TABLE 共用约定；若尚无则创建 `type=DOCUMENT`。

### 9.2 IMAGE 节点

```json
{
  "id": "image_1_d4e5f6",
  "label": "图1 系统架构图",
  "type": "IMAGE",
  "attributes": {
    "media_id": "img_a1b2c3d4_0000",
    "page_idx": 2,
    "route": "describe",
    "image_kind": "diagram",
    "final_kind": "description",
    "summary": "final_text 前 200 字",
    "source_ref": "{{IMAGE:img_a1b2c3d4_0000}}"
  }
}
```

label 优先级：`caption_raw` → `第{page_idx+1}页图片#{seq}` → `image_id`。

### 9.3 关系

| source | relation | target | 必要性 |
| --- | --- | --- | --- |
| DOCUMENT | `HAS_IMAGE` | IMAGE | **MUST** |
| IMAGE | `MENTIONS` | 文档既有实体 | SHOULD；可空 |

### 9.4 类型独占权

- `IMAGE` **仅流水线写入**；
- 文本 KG 抽取输出的 `IMAGE` MUST 丢弃或降为 `CONCEPT`。

---

## 10. 服务边界（逻辑接口）

```text
ImageAssetService.ensure_zip_assets(doc_id, content_list, zip_bytes) -> None
ImageAssetService.resolve(image_block) -> image_id, local_path

ImageRouter.route(image_bytes, caption, page_context, vlm_key) -> RouteDecision
ImageOCR.run(image_bytes, engine) -> OcrResult
ImageDescriber.describe(image_bytes, caption, page_context, vlm_key) -> DescriptionResult
ImageService.process_all(doc_id, content_list) -> list[ImageMeta]
ImageService.attach_to_kg(kg, metas) -> dict
```

约束：

- 路由与解析可对多图 **有界并发**（默认 3–5）；
- 单文档 VLM 调用上限（默认 40）超出部分用启发式 + 仅 caption，并记 `route.model=heuristic`；
- 路由层不得把 API Key 写入 meta。

---

## 11. 配置项

```text
VLM_MODEL=qwen/qwen2.5-vl-72b-instruct
VLM_MAX_IMAGE_SIDE=1568
VLM_MAX_IMAGES_PER_DOC=40
MEDIA_ROUTE_MIN_CONFIDENCE=0.55
IMAGE_DESC_MAX_TOKENS=512
OCR_ENGINE=rapidocr
OCR_LANG=ch
MIN_OCR_CHARS=10
OCR_MIN_AVG_CONFIDENCE=0.5
IMAGE_MIN_SIDE_PX=32
```

---

## 12. 失败与幂等

| 场景 | 行为 |
| --- | --- |
| 无 zip / 缺图 | `status=missing_asset`，可用 caption 建骨架节点 |
| 无 VLM Key | 启发式路由 + OCR 或仅 caption |
| 无 OCR 引擎 | 路由为 ocr 时改 describe 或 caption |
| 删除文档 | 删除 `media/{doc_id}/images/**` 与 KG IMAGE 节点 |

幂等：重建时 `image_id` 序列确定性；同 id 覆盖写文件与 meta。

---

## 13. 安全与合规

- 图片送第三方 VLM 前须用户配置并同意 OpenRouter Key；
- 日志禁止完整 base64；可记 `image_id`、尺寸、路由结果、耗时；
- 目录权限建议随 `doc_id` 归属校验（应用层强制 `owner_id`）。

---

## 14. 性能配额（初始）

| 项 | 建议 |
| --- | --- |
| 并发 | 3–5 |
| 单图 VLM 边长 | ≤1568 |
| 单文档 VLM 路由+描述调用 | ≤40 张（路由与描述各算一次） |
| 进度 | `media` 阶段内按已处理图片数更新 |

---

## 15. 验收标准

- [ ] 含图 PDF：zip 图片已落盘，`image_id` 与 content_list 对齐。
- [ ] 每张进入主流程的图有 `meta.json`，字段完整（ocr/describe 双侧 status 齐全）。
- [ ] 路由：截图类偏 ocr、图表/照片偏 describe；抽检 ≥20 张，人工一致率 ≥85% 为初验线。
- [ ] `final_text` 非空的图在 KG 有 IMAGE 节点与 `HAS_IMAGE` 边。
- [ ] 无 VLM Key：索引可完成，降级路径可追溯（`route.model` / `fallback`）。
- [ ] 无图文档：不因本模块失败。
- [ ] 重建无重复 `image_id`/节点。

---

## 16. 实施顺序（本规范独立交付）

1. zip 下载与图片落盘（修 `mineru_service`）
2. meta schema + caption 兼容
3. 启发式路由 + RapidOCR + final_text
4. VLM 路由 + VLM 描述 + 降级/并发/配额
5. KG 节点/边 + 抽取类型隔离
6. IndexTask `media` 阶段对接

---

## 17. 待确认项

| # | 问题 |
| --- | --- |
| 1 | VLM 最终模型与成本上限 |
| 2 | 是否保留原图 + 缩略图双份 |
| 3 | media 目录是否按 `owner_id` 分层 |
| 4 | 图表是否需要额外「结构化数据抽取」（超出 v1） |

---

## 18. 参考

- [MinerU Cloud API I/O](./mineru_cloud_api_io_spec_v1.0.md)（zip / images / content_list）
- OpenRouter Vision Messages API
- RapidOCR 文档
- [总览：PDF 多模态解析完善](./pdf-multimodal-parsing-spec-v1.0.md)
