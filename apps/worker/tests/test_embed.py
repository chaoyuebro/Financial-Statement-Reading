"""向量化阶段单测（db 桩 + 注入式 embedder，无需 torch / Postgres）。

验证：
- run_embed 按 (page, seq) 顺序 embed 并写回 embedding（512 维）
- embedder 收到的文本顺序与 chunks 一致
- 空 chunks 时不调用 write_embeddings
"""
import sys

sys.path.insert(0, "apps/worker")
import embed  # noqa: E402

# --- db 桩（避免真实 psycopg2 / Postgres）---
_CAP: dict = {}


def _read_chunks(report_id, version_tag):
    return [
        (1, 1, "text one"),
        (1, 2, "text two"),
        (2, 1, "text three"),
    ]


def _write_embeddings(report_id, version_tag, vectors):
    _CAP["rows"] = vectors
    return len(vectors)


embed.db.read_chunks = _read_chunks
embed.db.write_embeddings = _write_embeddings


def _fake_embedder(texts):
    # 512 维确定性向量（首元 = 文本下标），仅验证编排与顺序
    return [[float(i)] + [0.0] * 511 for i in range(len(texts))]


def test_run_embed_orders_and_writes():
    embed.set_embedder(_fake_embedder)
    _CAP.clear()
    res = embed.run_embed("rid", "cninfo", {"version_tag": "v1"})
    assert res["embedded"] == 3, res
    rows = _CAP["rows"]
    assert len(rows) == 3
    assert rows[0]["page"] == 1 and rows[0]["seq"] == 1
    assert rows[1]["page"] == 1 and rows[1]["seq"] == 2
    assert rows[2]["page"] == 2 and rows[2]["seq"] == 1
    assert len(rows[0]["embedding"]) == 512
    # 文本顺序：第 i 个 chunk -> 向量首元 = i
    assert rows[0]["embedding"][0] == 0.0
    assert rows[1]["embedding"][0] == 1.0
    assert rows[2]["embedding"][0] == 2.0


def test_run_embed_empty():
    embed.set_embedder(_fake_embedder)
    _CAP.clear()
    original = embed.db.read_chunks
    embed.db.read_chunks = lambda rid, vt: []
    try:
        res = embed.run_embed("rid", "cninfo", {"version_tag": "v1"})
        assert res["embedded"] == 0
        assert "rows" not in _CAP  # 无 chunk 不写 embedding
    finally:
        embed.db.read_chunks = original  # 还原，避免污染后续测试


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
