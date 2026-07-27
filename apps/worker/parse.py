"""Parser 阶段（技术方案 §6.2）。

- PyMuPDF 懒加载，逐页 get_text("text")（预研 #2：大 PDF 不超时、不 OOM）。
- 目录优先 get_toc()；若返回 OLE_LINK 垃圾或空，则从正文标题反推（预研 #3 兜底）。
- 文本按页切分为 ≤800 字符的 chunk，保留 page 映射（供 RAG 检索与前端高亮）。
- 幂等写入：document_chunks（先删旧再写）、disclosures.toc 回写。

TOC 输出对齐 packages/shared TocItem：{title, page, level}。
"""
from __future__ import annotations

import os
import re

import fitz

import config
import db

SEC_RE = re.compile(r"^第[一二三四五六七八九十百零]+节")
GARBAGE_BOOKMARK_RE = re.compile(
    r"^(?:OLE_LINK.*|RANGE![A-Z]+\$?\d+|_?PRINT_AREA|_?FILTERDATABASE)$",
    re.IGNORECASE,
)
MAX_CHUNK_CHARS = 800


def _pdf_cache_path(report_id: str, version_tag: str) -> str:
    safe = version_tag.replace(":", "_").replace("/", "_")
    return os.path.join(config.PDF_CACHE_DIR, f"{report_id}_{safe}.pdf")


def _split_page(text: str) -> list[str]:
    """将一页文本切分为 ≤800 字符的片段，优先在换行处断开；超长行/超长段硬切。"""
    text = text.rstrip("\n")
    if not text:
        return []
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    out: list[str] = []

    def _emit(seg: str) -> None:
        # 任何进入 out 的片段都强制不超过上限（超长行也会在此硬切）
        while len(seg) > MAX_CHUNK_CHARS:
            out.append(seg[:MAX_CHUNK_CHARS])
            seg = seg[MAX_CHUNK_CHARS:]
        if seg:
            out.append(seg)

    buf = ""
    for ln in text.split("\n"):
        if buf and len(buf) + len(ln) + 1 > MAX_CHUNK_CHARS:
            _emit(buf)
            buf = ln
        else:
            buf = (buf + "\n" + ln) if buf else ln
    if buf:
        _emit(buf)
    return out


def _derive_toc(pages_text: list[tuple[int, str]]) -> list[dict]:
    """正文标题反推目录（兜底）：抓「第X节」+ 下一行标题；跳过目录页。"""
    per_page: dict[int, int] = {}
    for pno, txt in pages_text:
        c = sum(1 for ln in txt.splitlines() if SEC_RE.match(ln.strip()))
        if c:
            per_page[pno] = c
    toc: list[dict] = []
    seen: set[str] = set()
    for pno, txt in pages_text:
        if per_page.get(pno, 0) > 3:  # 一页内 >3 个章节标题 → 判定为目录页，跳过
            continue
        lines = txt.splitlines()
        for idx, line in enumerate(lines):
            s = line.strip()
            if not SEC_RE.match(s):
                continue
            nxt = ""
            for n in lines[idx + 1 :]:
                if n.strip():
                    nxt = n.strip()
                    break
            title = (s + ((" " + nxt) if nxt else ""))[:34]
            key = s[:6]
            if key not in seen:
                seen.add(key)
                toc.append({"title": title, "page": pno, "level": 1})
    return toc


def _valid_bookmark(item: object, n_pages: int) -> bool:
    """过滤 Office 导出 PDF 时混入的内部命名区域和非法书签。"""
    if not isinstance(item, list) or len(item) <= 2:
        return False
    title = str(item[1]).strip()
    page = item[2]
    return bool(
        title
        and not GARBAGE_BOOKMARK_RE.fullmatch(title)
        and isinstance(page, int)
        and 1 <= page <= n_pages
    )


def parse_pdf(path: str) -> dict:
    """解析 PDF。返回 {n_pages, chunks, toc, toc_source}。

    chunks 元素：{page, seq(全局递增), text, meta}；meta 预留扩展位。
    """
    doc = fitz.open(path)
    n_pages = doc.page_count
    pages_text: list[tuple[int, str]] = []
    raw_chunks: list[dict] = []
    for pno in range(n_pages):
        txt = doc.load_page(pno).get_text("text")
        pages_text.append((pno + 1, txt))
        for seg in _split_page(txt):
            raw_chunks.append({"page": pno + 1, "text": seg, "meta": {}})

    toc_source = "PDF书签(get_toc)"
    try:
        raw = doc.get_toc()
        valid = [t for t in raw if _valid_bookmark(t, n_pages)]
        if valid:
            toc = [
                {
                    "title": t[1],
                    # PyMuPDF get_toc() 的页码本身就是 1-based。
                    "page": t[2],
                    "level": int(t[0]) if isinstance(t[0], int) else 1,
                }
                for t in valid
            ]
        else:
            toc = _derive_toc(pages_text)
            toc_source = "正文标题反推(兜底)"
    except Exception as e:  # noqa: BLE001
        toc = _derive_toc(pages_text)
        toc_source = f"正文标题反推(兜底, get_toc异常:{e})"

    doc.close()

    # 全局递增 seq，保证跨页稳定排序
    for i, ch in enumerate(raw_chunks):
        ch["seq"] = i
    return {
        "n_pages": n_pages,
        "chunks": raw_chunks,
        "toc": toc,
        "toc_source": toc_source,
    }


def run_parse(report_id: str, source: str, payload: dict | None = None) -> dict:
    """解析阶段入口：定位缓存 PDF → 解析 → 幂等写入 chunks + toc。"""
    payload = payload or {}
    pdf_path = payload.get("pdf_path")
    if not pdf_path:
        version_tag = db.version_tag_for(report_id, source)
        pdf_path = _pdf_cache_path(report_id, version_tag)
    if not os.path.isfile(pdf_path):
        raise RuntimeError(f"PDF 不存在，无法解析: {pdf_path}")

    result = parse_pdf(pdf_path)
    version_tag = db.version_tag_for(report_id, source)
    n = db.write_chunks(report_id, version_tag, result["chunks"])
    db.update_disclosure_toc(report_id, source, result["toc"])
    # 阶段自标记终态（状态机：parse → parsed）；pipeline 再设同值幂等
    db.set_report_status(report_id, config.STATUS_AFTER["parse"])
    return {
        "n_pages": result["n_pages"],
        "n_chunks": n,
        "n_toc": len(result["toc"]),
        "toc_source": result["toc_source"],
    }
