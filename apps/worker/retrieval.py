"""RAG 检索（技术方案 §7.3 / 预研#5）。

- 向量检索：生产走 pgvector 余弦相似度（db.search_chunks_vector）；
  纯 Python 余弦为本地/单测回退。
- 可选 BM25 RRF 重排提升精度。
- 引用二次校验：回答中的每个引用必须命中检索片段集合（§7.3 安全护栏 2）。
"""
from __future__ import annotations

import math
import re

import db

_TOKEN_RE = re.compile(r"[一-鿿]|[A-Za-z0-9]+")  # 粗分词：CJK 单字 + 英文/数字词


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


FINANCIAL_PHRASES = [
    ("营业收入", "营收"),
    ("归属于上市公司股东的净利润", "归母净利润"),
    ("经营活动产生的现金流量净额", "经营现金流"),
]


def financial_phrase_boost(text: str, query: str) -> float:
    """完整财务指标短语加权，避免向量近义项把主表挤出 top-k。"""
    score = 0.0
    for aliases in FINANCIAL_PHRASES:
        if not any(term in query for term in aliases):
            continue
        if any(term in text for term in aliases):
            score += 0.05
    return score


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def cosine_search(corpus: list[dict], query_vec: list[float], top_k: int = 8) -> list[dict]:
    """corpus: [{page,seq,text,embedding}]。纯 Python 余弦排序（本地/单测回退）。"""
    scored = []
    for c in corpus:
        emb = c.get("embedding")
        if not emb:
            continue
        scored.append({**c, "score": _cosine(query_vec, emb)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def bm25_scores(corpus: list[dict], query: str) -> dict[int, float]:
    """对 corpus(含 text) 计算 BM25。返回 {corpus下标: score}。"""
    q_tokens = tokenize(query)
    if not q_tokens:
        return {}
    n = len(corpus)
    df: dict[str, int] = {}
    for c in corpus:
        toks = set(tokenize(c.get("text", "")))
        for t in q_tokens:
            if t in toks:
                df[t] = df.get(t, 0) + 1
    idf = {
        t: math.log((n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5) + 1)
        for t in q_tokens
    }
    k1, b = 1.5, 0.75
    avgdl = sum(len(tokenize(c.get("text", ""))) for c in corpus) / max(n, 1)
    scores: dict[int, float] = {}
    for i, c in enumerate(corpus):
        toks = tokenize(c.get("text", ""))
        dl = len(toks)
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for t in q_tokens:
            f = tf.get(t)
            if not f:
                continue
            denom = f + k1 * (1 - b + b * dl / max(avgdl, 1))
            score += idf.get(t, 0) * (f * (k1 + 1)) / denom
        scores[i] = score
    return scores


def rrf_fuse(rankings: list[list[dict]], k: int = 60) -> dict[int, float]:
    """RRF 融合多个排序（每个 list 元素含 _idx）。返回 {_idx: fusion_score}。"""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            idx = item.get("_idx")
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return fused


def retrieve(
    report_id: str,
    question: str,
    top_k: int = 8,
    version_tag: str | None = None,
    use_rerank: bool = True,
    query_vec: list[float] | None = None,
) -> list[dict]:
    """生产入口：嵌问句 → pgvector 检索 → 可选 BM25 RRF 重排。

    返回 [{page, seq, text, score}]。query_vec 可注入便于单测。
    """
    if version_tag is None:
        version_tag = db.version_tag_for(report_id, db.primary_source_for(report_id))
    if query_vec is None:
        from embed import get_embedder

        query_vec = get_embedder()([question])[0]

    rows = db.search_chunks_vector(report_id, version_tag, query_vec, top_k * 2)
    vector_candidates = [
        {"page": r[0], "seq": r[1], "text": r[2], "score": r[3]}
        for r in rows
    ]
    corpus = vector_candidates
    if use_rerank:
        # BM25 必须从全文独立召回；若只重排向量候选，向量漏召回的主表永远无法进入结果。
        all_rows = db.read_chunks(report_id, version_tag)
        lexical_pool = [
            {"page": r[0], "seq": r[1], "text": r[2], "score": 0.0}
            for r in all_rows
        ]
        bm_all = bm25_scores(lexical_pool, question)
        lexical_candidates = sorted(
            enumerate(lexical_pool),
            key=lambda item: bm_all.get(item[0], 0.0),
            reverse=True,
        )[: top_k * 2]

        merged: dict[tuple[int, int], dict] = {
            (c["page"], c["seq"]): dict(c) for c in vector_candidates
        }
        for _, candidate in lexical_candidates:
            merged.setdefault((candidate["page"], candidate["seq"]), dict(candidate))
        corpus = list(merged.values())
        for i, c in enumerate(corpus):
            c["_idx"] = i
        index_by_key = {(c["page"], c["seq"]): c["_idx"] for c in corpus}
        vec_rank = [
            {**c, "_idx": index_by_key[(c["page"], c["seq"])]}
            for c in vector_candidates
        ]
        bm_rank = [
            {
                **candidate,
                "_idx": index_by_key[(candidate["page"], candidate["seq"])],
            }
            for _, candidate in lexical_candidates
        ]
        fused = rrf_fuse([vec_rank, bm_rank])
        for c in corpus:
            c["score"] = (
                fused.get(c["_idx"], 0.0)
                + financial_phrase_boost(c["text"], question)
            )
        corpus.sort(key=lambda c: c["score"], reverse=True)
    return [
        {"page": c["page"], "seq": c["seq"], "text": c["text"], "score": c["score"]}
        for c in corpus[:top_k]
    ]


def filter_citations(citations: list[dict], retrieved: list[dict]):
    """引用二次校验（§7.3）：仅保留 (page,text) 命中检索片段集合的引用。

    返回 (kept, dropped)。
    """
    allowed = {(c["page"], c["text"]) for c in retrieved}
    kept, dropped = [], []
    for cit in citations:
        if (cit.get("page"), cit.get("text")) in allowed:
            kept.append(cit)
        else:
            dropped.append(cit)
    return kept, dropped
