"""向量化阶段（技术方案 §6.4）。MVP 固定 bge-small-zh(512 维)。

- 模型**惰性加载**（sentence-transformers）；无 torch/GPU 环境不阻塞模块导入。
- embedder 可注入（set_embedder）便于单测，无需真实模型。
- run_embed：读 chunks → 逐 chunk 文本 embed → 幂等写 document_chunks.embedding。
"""
from __future__ import annotations

from collections.abc import Callable

import config
import db

# 注入式 embedder（单测用）；运行时为 None，惰性加载 bge-small-zh
_EMBEDDER_OVERRIDE = None
_EMBEDDER_RUNTIME = None


def get_embedder():
    """返回 encode(texts: list[str]) -> list[list[float]]（512 维）。"""
    global _EMBEDDER_OVERRIDE, _EMBEDDER_RUNTIME
    if _EMBEDDER_OVERRIDE is not None:
        return _EMBEDDER_OVERRIDE
    if _EMBEDDER_RUNTIME is not None:
        return _EMBEDDER_RUNTIME
    from fastembed import TextEmbedding

    model = TextEmbedding(
        model_name=config.EMBEDDING_MODEL,
        cache_dir=config.EMBEDDING_CACHE_DIR,
    )

    def _encode(texts: list[str]) -> list[list[float]]:
        vecs = [list(map(float, v)) for v in model.embed(texts, batch_size=32)]
        if vecs and len(vecs[0]) != config.EMBEDDING_DIM:
            raise RuntimeError(
                f"embedding 维度不匹配: got={len(vecs[0])}, expected={config.EMBEDDING_DIM}"
            )
        return vecs

    _EMBEDDER_RUNTIME = _encode
    return _EMBEDDER_RUNTIME


def set_embedder(fn) -> None:
    """注入自定义 embedder（单测用）。fn(texts)->list[list[float]]。"""
    global _EMBEDDER_OVERRIDE
    _EMBEDDER_OVERRIDE = fn


def run_embed(
    report_id: str,
    source: str,
    payload: dict | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict:
    """阶段入口：读 chunks → embed → 幂等写 embedding。"""
    payload = payload or {}
    version_tag = payload.get("version_tag") or db.version_tag_for(report_id, source)

    chunks = db.read_chunks(report_id, version_tag)
    if not chunks:
        return {"embedded": 0}
    # 保持 (page, seq) 顺序，逐 chunk 文本 embed
    keys: list[tuple[int, int]] = []
    by_key: dict[tuple[int, int], str] = {}
    for page, seq, text in chunks:
        k = (page, seq)
        keys.append(k)
        by_key[k] = text

    embedder = get_embedder()
    batch_size = 32
    embedded = 0
    total = len(keys)
    for start in range(0, total, batch_size):
        batch_keys = keys[start : start + batch_size]
        vecs = embedder([by_key[k] for k in batch_keys])
        vectors = [
            {"page": k[0], "seq": k[1], "embedding": vecs[i]}
            for i, k in enumerate(batch_keys)
        ]
        embedded += db.write_embeddings(report_id, version_tag, vectors)
        if progress_callback is not None:
            progress_callback(min(start + len(batch_keys), total), total)
    return {"embedded": embedded}
