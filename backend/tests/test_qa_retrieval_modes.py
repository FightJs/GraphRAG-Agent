"""检索模式分化单测：kg_only 只走图谱，agentic 子查询三路召回 + RRF"""
from app.services import qa_service


_SAMPLE_KG = {
    "nodes": [
        {"id": "n1", "label": "纤毫匠心核雕文创", "type": "PROJECT", "attributes": {}},
        {"id": "n2", "label": "苏州核雕", "type": "CONCEPT", "attributes": {}},
        {"id": "n3", "label": "苏州舟山村", "type": "LOCATION", "attributes": {}},
        {"id": "n4", "label": "非遗传承人", "type": "POSITION", "attributes": {}},
        {"id": "n5", "label": "SEM结构方程模型", "type": "CONCEPT", "attributes": {}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2", "relation": "立足于"},
        {"id": "e2", "source": "n1", "target": "n3", "relation": "合作"},
        {"id": "e3", "source": "n3", "target": "n4", "relation": "拥有"},
        {"id": "e4", "source": "n1", "target": "n5", "relation": "采用"},
    ],
}

_SAMPLE_CHUNKS = [
    {
        "text": "SEM分析显示，现有消费者的购买行为受魅力属性（路径系数0.890***）驱动。",
        "page_idx": 2,
        "chunk_index": 0,
    },
    {
        "text": "项目拟天使轮融资 RMB 200 万元，释放 10%-15% 股权。",
        "page_idx": 4,
        "chunk_index": 1,
    },
]


class TestNormalizeMode:
    def test_valid_modes(self):
        assert qa_service._normalize_mode("kg_only") == "kg_only"
        assert qa_service._normalize_mode("agentic") == "agentic"

    def test_legacy_aliases_map_to_agentic(self):
        assert qa_service._normalize_mode("hybrid") == "agentic"
        assert qa_service._normalize_mode("semantic") == "agentic"
        assert qa_service._normalize_mode("HYBRID") == "agentic"

    def test_invalid_falls_back(self):
        assert qa_service._normalize_mode("unknown") == "kg_only"
        assert qa_service._normalize_mode(None) == "kg_only"
        assert qa_service._normalize_mode("") == "kg_only"

    def test_auto_small_graph_stays_kg_only(self):
        kg = {"nodes": [{"id": f"n{i}"} for i in range(10)]}
        assert qa_service._normalize_mode("auto", kg) == "kg_only"

    def test_auto_large_graph_switches_agentic(self):
        kg = {"nodes": [{"id": f"n{i}"} for i in range(201)]}
        assert qa_service._normalize_mode("auto", kg) == "agentic"


class TestKgSummaryUsesLabels:
    def test_edges_render_labels_not_ids(self):
        text = qa_service._kg_summary(_SAMPLE_KG)
        assert "纤毫匠心核雕文创 --[立足于]--> 苏州核雕" in text
        assert "n1 --[" not in text


class TestSelectKgSubgraph:
    def test_question_hits_expand_one_hop(self):
        sub = qa_service._select_kg_for_question(_SAMPLE_KG, "纤毫匠心和苏州舟山村是什么关系？")
        labels = {n["label"] for n in sub["nodes"]}
        assert "纤毫匠心核雕文创" in labels
        assert "苏州舟山村" in labels
        assert "非遗传承人" in labels  # 一跳邻居

    def test_no_hit_returns_empty_subgraph(self):
        sub = qa_service._select_kg_for_question(_SAMPLE_KG, "完全无关的问题xyz")
        assert sub["nodes"] == []
        assert sub["edges"] == []

    def test_two_hop_neighbors_included(self):
        kg = {
            "nodes": [
                {"id": "a", "label": "甲公司", "type": "COMPANY", "attributes": {}},
                {"id": "b", "label": "乙项目", "type": "PROJECT", "attributes": {}},
                {"id": "c", "label": "丙人物", "type": "PERSON", "attributes": {}},
                {"id": "d", "label": "丁学校", "type": "SCHOOL", "attributes": {}},
            ],
            "edges": [
                {"id": "e1", "source": "a", "target": "b", "relation": "投资"},
                {"id": "e2", "source": "b", "target": "c", "relation": "负责人"},
                {"id": "e3", "source": "c", "target": "d", "relation": "毕业"},
            ],
        }
        sub = qa_service._select_kg_for_question(kg, "甲公司")
        labels = {n["label"] for n in sub["nodes"]}
        assert "甲公司" in labels
        assert "乙项目" in labels  # 1-hop
        assert "丙人物" in labels  # 2-hop


class TestBuildRetrievalContext:
    def test_kg_only_excludes_chunks_and_sources(self):
        ctx, sources, mode = qa_service._build_retrieval_context(
            _SAMPLE_KG, _SAMPLE_CHUNKS, "SEM路径系数是多少？", "kg_only",
            doc_id="d1", doc_title="demo.pdf",
        )
        assert mode == "kg_only"
        assert sources == []
        assert "相关文档片段" not in ctx
        assert "0.890" not in ctx
        assert "知识图谱" in ctx

    def test_agentic_includes_chunks_and_sources(self):
        ctx, sources, mode = qa_service._build_retrieval_context(
            _SAMPLE_KG, _SAMPLE_CHUNKS, "SEM路径系数是多少？", "agentic",
            doc_id="d1", doc_title="demo.pdf",
        )
        assert mode == "agentic"
        assert "相关文档片段" in ctx
        assert "0.890" in ctx
        assert len(sources) >= 1
        src = sources[0]
        assert src["doc_name"] == "demo.pdf"
        assert src["page"] == 3  # page_idx=2 → 第3页
        assert src["excerpt"]
        assert "0.890" in src["excerpt"] or "SEM" in src["excerpt"]

    def test_agentic_also_contains_kg(self):
        ctx, _, mode = qa_service._build_retrieval_context(
            _SAMPLE_KG, _SAMPLE_CHUNKS, "SEM路径系数是多少？", "agentic",
            doc_id="d1", doc_title="demo.pdf",
        )
        assert "知识图谱" in ctx
        assert "SEM结构方程模型" in ctx
        assert "魅力属性" in ctx

    def test_same_question_modes_differ(self):
        """同题：kg_only 无原文，agentic 有原文与来源"""
        q = "SEM路径系数是多少？"
        c1, s1, _ = qa_service._build_retrieval_context(
            _SAMPLE_KG, _SAMPLE_CHUNKS, q, "kg_only", doc_id="d1", doc_title="demo.pdf"
        )
        c2, s2, _ = qa_service._build_retrieval_context(
            _SAMPLE_KG, _SAMPLE_CHUNKS, q, "agentic", doc_id="d1", doc_title="demo.pdf"
        )
        assert s1 == [] and "【相关文档片段】" not in c1
        assert len(s2) >= 1 and "【相关文档片段】" in c2
        assert c1 != c2

    def test_kg_only_never_has_sources(self):
        _, sources, mode = qa_service._build_retrieval_context(
            _SAMPLE_KG, _SAMPLE_CHUNKS, "SEM路径系数是多少？", "kg_only",
            doc_id="d1", doc_title="demo.pdf",
        )
        assert mode == "kg_only"
        assert sources == []

    def test_mock_answer_respects_empty_subgraph(self):
        assert "未找到" in qa_service._mock_answer("任意问题", {"nodes": [], "edges": []})


class TestChunkToSource:
    def test_page_and_excerpt(self):
        src = qa_service._chunk_to_source(
            {"text": "x" * 200, "page_idx": 0}, "doc1", "a.pdf"
        )
        assert src["page"] == 1
        assert src["excerpt"].endswith("...")
        assert src["doc_id"] == "doc1"
        assert src["doc_name"] == "a.pdf"
        assert src["doc_title"] == "a.pdf"
        assert src["snippet"] == src["excerpt"]


class TestRrfFuse:
    def test_overlap_ranks_higher(self):
        a = [{"chunk_id": "c1", "text": "t1", "source": "vector"},
             {"chunk_id": "c2", "text": "t2", "source": "vector"}]
        b = [{"chunk_id": "c1", "text": "t1", "source": "keyword"},
             {"chunk_id": "c3", "text": "t3", "source": "keyword"}]
        fused = qa_service._rrf_fuse([a, b], k=60)
        assert fused[0]["chunk_id"] == "c1"
        assert fused[0]["source"] == "rrf:keyword+vector"
        ids = [h["chunk_id"] for h in fused]
        assert set(ids) == {"c1", "c2", "c3"}

    def test_single_list_preserves_order(self):
        a = [{"chunk_id": "c2", "text": "t2", "source": "keyword"},
             {"chunk_id": "c1", "text": "t1", "source": "keyword"}]
        fused = qa_service._rrf_fuse([a], k=60)
        assert [h["chunk_id"] for h in fused] == ["c2", "c1"]
        assert abs(fused[0]["score"] - 1.0 / 61) < 1e-9

    def test_empty_lists(self):
        assert qa_service._rrf_fuse([], k=60) == []
        assert qa_service._rrf_fuse([[], []], k=60) == []


class TestRrfAgentic:
    def test_decompose_queries_contains_original(self):
        qs = qa_service._decompose_queries("SEM路径系数是多少？融资金额呢？")
        assert qs[0] == "SEM路径系数是多少？融资金额呢？"
        assert len(qs) >= 2
        assert len(qs) <= 3

    def test_agentic_retrieve_three_way_context(self, monkeypatch):
        monkeypatch.setattr(qa_service, "_load_chunks", lambda doc_id: _SAMPLE_CHUNKS)

        import asyncio
        ctx, sources, sub_qs = asyncio.run(
            qa_service._agentic_retrieve(
                user_id="u1",
                question="SEM路径系数是多少？融资金额呢？",
                doc_id="d1",
                doc_title="demo.pdf",
                kg=_SAMPLE_KG,
            )
        )
        assert "RRF Agentic" in ctx or "三路召回" in ctx
        assert "0.890" in ctx or "200" in ctx
        assert "知识图谱" in ctx
        assert len(sub_qs) >= 1
        assert len(sources) >= 1
