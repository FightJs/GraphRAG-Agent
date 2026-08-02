"""
Agentic-RAG MVP — KG-only Q&A Pipeline
=======================================
Flow:
  content_list.json
    → [Stage 2] Bridge Layer (mineru_to_text)   → List[lx.Document]
    → [Stage 3] LangExtract + DeepSeek          → AnnotatedDocument
    → [Stage 4] graph_builder                    → knowledge_graph.json
    → [Stage 5] LangChain Q&A (DeepSeek)         → Answer

规范依据: docs/bridgepipeline-spec-v1.0.md
运行环境: bridge_pipeline/.venv (source bridge_pipeline/.venv/bin/activate)
"""

import sys
import json
import os
from pathlib import Path

# ── Path setup: import bridge_pipeline modules ────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bridge_pipeline"))

import langextract as lx
from langextract.providers.openai import OpenAILanguageModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from mineru_to_text import content_list_to_documents
from graph_builder import build_knowledge_graph, save_knowledge_graph

# ── Config ────────────────────────────────────────────────────────────────────
DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL    = "deepseek-chat"

# MinerU 已解析的简历 content_list.json（d2b8e67e = 肖超简历）
CONTENT_LIST_PATH = ROOT / "bridge_pipeline/output/d2b8e67e/content_list.json"
PDF_STEM          = "肖超-应届生年经验-Agent_开发工程师"

OUTPUT_DIR        = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
KG_JSON_PATH      = OUTPUT_DIR / "kg_resume.json"
KG_JSONL_PATH     = OUTPUT_DIR / "kg_resume.jsonl"

# ── Stage 2: Bridge Layer ─────────────────────────────────────────────────────
def stage2_bridge() -> list:
    """content_list.json → List[lx.data.Document]"""
    print("\n[Stage 2] Bridge: content_list.json → List[Document]")
    docs = content_list_to_documents(
        content_list_path=str(CONTENT_LIST_PATH),
        pdf_stem=PDF_STEM,
        split_by="page",
        include_tables=True,
    )
    print(f"  ✓ {len(docs)} documents")
    for d in docs:
        preview = d.text[:60].replace("\n", " ")
        print(f"    {d.document_id}: {len(d.text)} chars | {preview}…")
    return docs


# ── Stage 3: KG Extraction ────────────────────────────────────────────────────
PROMPT_KG = """
从简历文本中提取以下实体和关系，用于构建候选人知识图谱：

实体类型：
- 实体_人物：候选人姓名
- 实体_技能：技术技能、编程语言、框架、工具（如Python、LangChain、RAG等）
- 实体_项目：参与过的项目名称
- 实体_公司：就职或实习的公司或机构名称
- 实体_学校：就读院校名称
- 实体_职位：申请或担任过的职位名称

关系（extraction_class 固定为"关系"，attributes 必须含主体/客体/关系类型）：
- 候选人 掌握 技能
- 候选人 参与 项目
- 候选人 就职于/实习于 公司
- 候选人 毕业于 学校
- 项目 使用了 技术/工具
"""

EXAMPLES_KG = [
    lx.data.ExampleData(
        text="张三，Python开发工程师，熟悉LangChain框架，曾在阿里巴巴实习六个月",
        extractions=[
            lx.data.Extraction(extraction_class="实体_人物",  extraction_text="张三"),
            lx.data.Extraction(extraction_class="实体_技能",  extraction_text="Python"),
            lx.data.Extraction(extraction_class="实体_技能",  extraction_text="LangChain"),
            lx.data.Extraction(extraction_class="实体_公司",  extraction_text="阿里巴巴"),
            lx.data.Extraction(
                extraction_class="关系",
                extraction_text="张三熟悉LangChain框架",
                attributes={"主体": "张三", "客体": "LangChain", "关系类型": "掌握"},
            ),
            lx.data.Extraction(
                extraction_class="关系",
                extraction_text="张三曾在阿里巴巴实习",
                attributes={"主体": "张三", "客体": "阿里巴巴", "关系类型": "实习于"},
            ),
        ],
    )
]


def _serialize_annotated_doc(doc) -> str:
    """AnnotatedDocument → JSON line（兼容 bridgepipeline-spec §三·3.3）"""
    extractions = []
    for e in (doc.extractions or []):
        ci = e.char_interval
        extractions.append({
            "extraction_class":  e.extraction_class,
            "extraction_text":   e.extraction_text,
            "char_interval":     {"start_pos": ci.start_pos, "end_pos": ci.end_pos} if ci else None,
            "alignment_status":  e.alignment_status.value if e.alignment_status else None,
            "extraction_index":  e.extraction_index,
            "group_index":       e.group_index,
            "description":       e.description,
            "attributes":        e.attributes,
        })
    return json.dumps(
        {"extractions": extractions, "text": doc.text, "document_id": doc.document_id},
        ensure_ascii=False,
    )


def stage3_extract_kg(documents: list) -> list:
    """List[Document] → List[AnnotatedDocument]，结果写入 kg_resume.jsonl"""
    print("\n[Stage 3] LangExtract: Document → KG AnnotatedDocument")
    lx_model = OpenAILanguageModel(
        model_id=DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        temperature=0.0,
    )
    results = lx.extract(
        text_or_documents=documents,
        prompt_description=PROMPT_KG,
        examples=EXAMPLES_KG,
        model=lx_model,
        max_char_buffer=2000,
        context_window_chars=300,
    )
    total_ext = sum(len(r.extractions or []) for r in results)
    print(f"  ✓ {len(results)} annotated docs, {total_ext} extractions")

    with open(KG_JSONL_PATH, "w", encoding="utf-8") as f:
        for r in results:
            f.write(_serialize_annotated_doc(r) + "\n")
    print(f"  ✓ Saved → {KG_JSONL_PATH}")
    return results


# ── Stage 4: Build Knowledge Graph ───────────────────────────────────────────
def stage4_build_kg(annotated_docs: list) -> dict:
    """AnnotatedDocument → knowledge_graph.json（nodes + edges）"""
    print("\n[Stage 4] Build Knowledge Graph")
    kg = build_knowledge_graph(annotated_docs, pdf_stem=PDF_STEM)
    save_knowledge_graph(kg, str(KG_JSON_PATH))
    m = kg["meta"]
    print(f"  ✓ Nodes: {m['total_nodes']}  Edges: {m['total_edges']}")
    print(f"  ✓ Saved → {KG_JSON_PATH}")

    print("\n  -- 节点预览 --")
    for node in kg["nodes"][:8]:
        attrs = node.get("attributes", {})
        attr_str = f"  {attrs}" if attrs else ""
        print(f"    [{node['type']}] {node['id']}{attr_str}")
    if len(kg["nodes"]) > 8:
        print(f"    … 共 {len(kg['nodes'])} 个节点")

    print("\n  -- 关系预览 --")
    for edge in kg["edges"][:8]:
        print(f"    {edge['source']} --[{edge['relation']}]--> {edge['target']}")
    if len(kg["edges"]) > 8:
        print(f"    … 共 {len(kg['edges'])} 条关系")
    return kg


# ── Stage 5: KG Q&A via LangChain + DeepSeek ─────────────────────────────────
def _kg_to_context(kg: dict) -> str:
    """将整个知识图谱序列化为 LLM 可读的上下文字符串。"""
    lines = ["=== 候选人知识图谱 ===", ""]
    lines.append("【节点（实体）】")
    for node in kg["nodes"]:
        attrs = node.get("attributes") or {}
        attr_str = "  属性: " + json.dumps(attrs, ensure_ascii=False) if attrs else ""
        lines.append(f"  · [{node['type']}] {node['id']}{attr_str}")
    lines.append("")
    lines.append("【关系（边）】")
    for edge in kg["edges"]:
        evidence = f'  （原文: {edge["text"]}）' if edge.get("text") else ""
        lines.append(f"  · {edge['source']} --[{edge['relation']}]--> {edge['target']}{evidence}")
    return "\n".join(lines)


def create_kg_qa(kg: dict):
    """
    返回一个 qa(question) -> str 函数。
    使用 LangChain ChatOpenAI 接入 DeepSeek，严格遵循 LangChain 官方规范。
    参考: https://python.langchain.com/docs/integrations/chat/openai/
    """
    llm = ChatOpenAI(
        model=DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        temperature=0,
        max_tokens=1024,
    )
    kg_context = _kg_to_context(kg)

    def qa(question: str) -> str:
        messages = [
            SystemMessage(content=(
                "你是一位候选人信息查询助手，基于以下知识图谱回答关于候选人的问题。\n"
                "仅使用知识图谱中的信息，不要编造内容。\n\n"
                + kg_context
            )),
            HumanMessage(content=question),
        ]
        return llm.invoke(messages).content

    return qa


# ── Main: 全流程运行 + 连通性测试 ─────────────────────────────────────────────
TEST_QUESTIONS = [
    "候选人叫什么名字？求职目标是什么职位？",
    "候选人掌握哪些技术技能和框架？请列举主要技能。",
    "候选人参与过哪些项目？每个项目用了哪些技术？",
    "候选人的教育背景是什么？毕业院校和专业？",
    "请为这位候选人做一个综合评估，判断是否适合 Agent 开发工程师岗位。",
]


def main():
    print("=" * 62)
    print("  Agentic-RAG MVP  —  KG Q&A Pipeline  (DeepSeek + LangChain)")
    print("=" * 62)

    # Pipeline
    docs       = stage2_bridge()
    annotated  = stage3_extract_kg(docs)
    kg         = stage4_build_kg(annotated)

    # Q&A 连通性测试
    print("\n" + "=" * 62)
    print("  [Stage 5] KG Q&A 连通性测试")
    print("=" * 62)
    qa = create_kg_qa(kg)

    for i, q in enumerate(TEST_QUESTIONS, 1):
        print(f"\n【Q{i}】{q}")
        print(f"【A{i}】{qa(q)}")

    print("\n" + "=" * 62)
    print("  ✓  MVP 全流程测试完成")
    print(f"  输出文件:")
    print(f"    KG JSONL : {KG_JSONL_PATH}")
    print(f"    KG JSON  : {KG_JSON_PATH}")
    print("=" * 62)


if __name__ == "__main__":
    main()
