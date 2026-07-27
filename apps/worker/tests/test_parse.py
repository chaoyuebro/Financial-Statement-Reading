"""Parser 阶段单测（W3-4c）。

说明：PyMuPDF 的 insert_text 不生成 ToUnicode CMap，CJK 无法经 get_text 回读
（真实 PDF 内嵌字体则正常，见 parse_stress.py）。因此：
- 书签路径：用真实 PDF + set_toc 验证（书签是元数据，不依赖文本回读）。
- derive_toc 兜底：直接喂合成 pages_text（中文标题）验证正则与目录页跳过。
- chunk 切分：直接单测 _split_page + 经 ASCII 文本 PDF 验证 run_parse 集成。
对 db 层做桩，无需 Postgres。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz

import db  # 桩替换其写入函数
import parse


class _Recorder:
    def __init__(self):
        self.chunks = None
        self.toc = None
        self.wrote = 0

    def version_tag_for(self, report_id, source):
        return f"{source}:ANN123"

    def write_chunks(self, report_id, version_tag, chunks):
        self.chunks = chunks
        self.wrote = len(chunks)
        return len(chunks)

    def update_disclosure_toc(self, report_id, source, toc):
        self.toc = toc

    def set_report_status(self, report_id, status):
        self.status = status


def _make_bookmark_pdf(path: str):
    doc = fitz.open()
    p0 = doc.new_page()
    p0.insert_text((50, 50), "目录\n第一节\n第二节\n第三节\n第四节\n第五节")
    p1 = doc.new_page()
    p1.insert_text((50, 50), "第一节 概览\n本期营业收入为 1,234,567 元。")
    p2 = doc.new_page()
    p2.insert_text((50, 50), "第二节 财务\n经营活动产生的现金流量净额为 234,567 元。")
    doc.set_toc([(1, "第一节 概览", 1), (1, "第二节 财务", 2)])
    doc.save(path)
    doc.close()


def test_parse_with_bookmarks():
    rec = _Recorder()
    _patch_db(rec)
    with tempfile.TemporaryDirectory() as d:
        pdf = os.path.join(d, "r.pdf")
        _make_bookmark_pdf(pdf)
        res = parse.run_parse("rep-1", "cninfo", {"pdf_path": pdf})
    assert res["n_pages"] == 3
    assert res["n_toc"] >= 2, "书签路径应产出 toc"
    assert rec.toc is not None and len(rec.toc) >= 2
    assert all("title" in t and "page" in t and "level" in t for t in rec.toc)
    assert rec.wrote > 0
    assert all(c["page"] >= 1 and "text" in c and "seq" in c for c in rec.chunks)
    print(f"[bookmarks] toc={res['n_toc']} chunks={res['n_chunks']} src={res['toc_source']}")


def test_derive_toc_unit():
    # 合成 pages_text：第1页为目录页(>3标题, 应跳过)，第2/3页为正文标题
    pages_text = [
        (1, "目录\n第一节 概览\n第二节 财务\n第三节 治理\n第四节 风险\n第五节 附注"),
        (2, "第一节 概览\n本期营业收入为 1,234,567 元。"),
        (3, "第二节 财务\n经营活动产生的现金流量净额为 234,567 元。"),
    ]
    toc = parse._derive_toc(pages_text)
    assert len(toc) >= 1, "兜底应反推出至少 1 条"
    assert all(t["page"] > 1 for t in toc), "目录页(第1页)应被跳过"
    assert all("title" in t and "page" in t and "level" in t for t in toc)
    print(f"[derive_toc] toc={len(toc)} -> {[t['title'] for t in toc]}")


def test_garbage_office_bookmarks_are_rejected():
    assert not parse._valid_bookmark([1, "RANGE!E9", 74], 100)
    assert not parse._valid_bookmark([1, "OLE_LINK12", 2], 100)
    assert not parse._valid_bookmark([1, "Print_Area", 3], 100)
    assert parse._valid_bookmark([1, "第六节 重要事项", 74], 100)


def test_split_page_unit():
    s = "A" * 1000  # 单行长文本，验证硬切分
    parts = parse._split_page(s)
    assert len(parts) >= 2, "超长单行应被切分为多个 chunk"
    assert all(len(p) <= parse.MAX_CHUNK_CHARS for p in parts), "单 chunk 不得超过上限"
    # 多行且含换行
    multi = "短行一\n" + "B" * 900 + "\n短行三"
    parts2 = parse._split_page(multi)
    assert all(len(p) <= parse.MAX_CHUNK_CHARS for p in parts2)
    print(f"[split] single_line_chunks={len(parts)} multi_chunks={len(parts2)}")


def test_parse_chunk_from_pdf():
    rec = _Recorder()
    _patch_db(rec)
    with tempfile.TemporaryDirectory() as d:
        pdf = os.path.join(d, "big.pdf")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "A" * 1000)
        doc.save(pdf)
        doc.close()
        res = parse.run_parse("rep-3", "cninfo", {"pdf_path": pdf})
    assert all(len(c["text"]) <= parse.MAX_CHUNK_CHARS for c in rec.chunks), "chunk 不超上限"
    print(f"[chunk] n_chunks={res['n_chunks']} max_len={max(len(c['text']) for c in rec.chunks)}")


# ---- 简易 db 桩（避免导入真实 psycopg2 / Postgres）----
_DB_STUB_NAMES = ("version_tag_for", "write_chunks", "update_disclosure_toc", "set_report_status")
_TRUE_ORIG = {name: getattr(db, name) for name in _DB_STUB_NAMES}


def _patch_db(rec):
    for name in _DB_STUB_NAMES:
        setattr(db, name, getattr(rec, name))


def _restore_db():
    for name, fn in _TRUE_ORIG.items():
        setattr(db, name, fn)


if __name__ == "__main__":
    tests = [
        test_parse_with_bookmarks,
        test_derive_toc_unit,
        test_garbage_office_bookmarks_are_rejected,
        test_split_page_unit,
        test_parse_chunk_from_pdf,
    ]
    passed = 0
    for fn in tests:
        _patch_db(_Recorder())
        try:
            fn()
            _restore_db()
            print(f"PASS {fn.__name__}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            _restore_db()
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
