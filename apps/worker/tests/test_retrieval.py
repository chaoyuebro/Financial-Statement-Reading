"""RAG 检索单测（纯逻辑 + db 桩，无需 pgvector / 模型）。

覆盖：余弦排序、BM25、RRF 融合、retrieve 编排（注入 query_vec + db 桩）、引用二次校验。
"""
import sys

sys.path.insert(0, "apps/worker")
import retrieval  # noqa: E402

# ---- db 桩 ----
_ROWS = [
    (1, 1, "营收增长主要来自茅台酒", 0.90),
    (2, 1, "公司实现营业收入 100 亿", 0.70),
    (3, 2, "经营现金流净额为负", 0.40),
]
retrieval.db.search_chunks_vector = lambda rid, vt, qv, k=8: _ROWS[:k]
retrieval.db.read_chunks = lambda rid, vt: [(r[0], r[1], r[2]) for r in _ROWS]


def test_cosine_search_ordering():
    corpus = [
        {"page": 1, "seq": 1, "text": "A", "embedding": [0, 1, 0]},
        {"page": 2, "seq": 1, "text": "B", "embedding": [1, 0, 0]},
        {"page": 3, "seq": 1, "text": "C", "embedding": [0, 0, 1]},
    ]
    out = retrieval.cosine_search(corpus, [1, 0, 0], top_k=3)
    assert out[0]["text"] == "B"
    assert out[1]["text"] == "A"
    assert out[2]["text"] == "C"


def test_bm25_favors_matching_doc():
    corpus = [
        {"text": "营业收入 增长 主要 来自 茅台酒"},
        {"text": "现金流 净额 为负"},
    ]
    bm = retrieval.bm25_scores(corpus, "营业收入")
    assert bm[0] > bm[1], bm


def test_rrf_fuse_sums_ranks():
    r1 = [{"_idx": 0}, {"_idx": 1}]
    r2 = [{"_idx": 1}, {"_idx": 0}]
    fused = retrieval.rrf_fuse([r1, r2])
    # idx0: rank0 (1/61) + rank1 (1/62); idx1: rank1 (1/62) + rank0 (1/61) -> 相等
    assert abs(fused[0] - fused[1]) < 1e-9, fused
    assert fused[0] > 1.0 / 61


def test_retrieve_orders_by_vector_score():
    out = retrieval.retrieve(
        "rid", "任意问题", top_k=3, version_tag="v1",
        use_rerank=False, query_vec=[0.1, 0.2],
    )
    assert [o["page"] for o in out] == [1, 2, 3]
    assert out[0]["score"] == 0.90


def test_retrieve_rerank_keeps_set():
    out = retrieval.retrieve(
        "rid", "营业收入", top_k=3, version_tag="v1",
        use_rerank=True, query_vec=[0.1, 0.2],
    )
    assert len(out) == 3
    assert {o["page"] for o in out} == {1, 2, 3}


def test_filter_citations_drops_unretrieved():
    retrieved = [
        {"page": 1, "seq": 1, "text": "营收增长主要来自茅台酒"},
        {"page": 2, "seq": 1, "text": "公司实现营业收入 100 亿"},
        {"page": 3, "seq": 2, "text": "经营现金流净额为负"},
    ]
    citations = [
        {"page": 1, "text": "营收增长主要来自茅台酒"},  # 命中
        {"page": 9, "text": "报告中未披露的内容"},        # 未检索到 → 丢弃
    ]
    kept, dropped = retrieval.filter_citations(citations, retrieved)
    assert len(kept) == 1 and kept[0]["page"] == 1
    assert len(dropped) == 1 and dropped[0]["page"] == 9


def test_financial_phrase_boost_prefers_complete_metric_terms():
    query = "营业收入和归母净利润分别是多少"
    main_table = (
        "营业收入 168,838,102,514.79 "
        "归属于上市公司股东的净利润 82,320,067,101.68"
    )
    assert retrieval.financial_phrase_boost(main_table, query) == 0.1
    assert retrieval.financial_phrase_boost("营业收入变化原因", query) == 0.05


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
