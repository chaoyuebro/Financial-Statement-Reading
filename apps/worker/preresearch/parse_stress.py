# -*- coding: utf-8 -*-
"""预研 #2/#3/#4 (终版): 大 PDF 解析 + 页码映射 + 指标抽取 + 正文反推目录兜底
关键修正:
- 目录用 get_toc(); 若返回 OLE_LINK 垃圾/空, 则从正文标题反推 (兜底)
- 指标: 归一化换行后匹配关键词(防标签被切断); 遍历所有出现, 仅在标签后有限窗口取货币数字
"""
import os, re, time, json, tracemalloc

try:
    import fitz
except Exception as e:
    raise SystemExit("PyMuPDF 未安装: " + str(e))

RESEARCH = "C:/Users/baibai/.workbuddy/research"
OUT_DIR = os.path.join(RESEARCH, "parsed")
os.makedirs(OUT_DIR, exist_ok=True)

TARGETS = [
    ("茅台2022年报", "C:/Users/baibai/600519_年报_1216281757.pdf"),
    ("强一股份招股书(大)", "C:/Users/baibai/.workbuddy/research/downloads/qylc_prospectus.pdf"),
]

def parse_number(s):
    s = s.strip()
    neg = s.startswith("(") or s.startswith("-") or s.startswith("\u2212")
    s = s.strip("()").replace(",", "").replace("\u2212", "-")
    try:
        return -float(s) if neg else float(s)
    except Exception:
        return None

MONEY_RE = re.compile(r"\(?-?[\d,]{1,3}(?:,\d{3})+(?:\.\d+)?\)?|-?[\d,]{6,}(?:\.\d+)?")
YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")

def first_money(s):
    for m in MONEY_RE.finditer(s):
        tok = m.group(0)
        if YEAR_RE.match(re.sub(r"[^\d]", "", tok)):
            continue
        v = parse_number(tok)
        if v is not None:
            return v, tok
    return None, None

METRICS = {
    "营业收入": ["营业收入", "营业总收入"],
    "归母净利润": ["归属于上市公司股东的净利润", "归属于母公司股东的净利润", "归母净利润"],
    "经营现金流净额": ["经营活动产生的现金流量净额", "经营活动现金净额"],
}

# 关键词正则: 允许词内被换行/空格切断 (防 "归属于上市公司股\n东的净利润")
KW_CACHE = {}
def kw_regex(k):
    if k not in KW_CACHE:
        KW_CACHE[k] = re.compile(r"\s*".join(re.escape(c) for c in k))
    return KW_CACHE[k]

def find_metric(pages_text, section_pages):
    res = {}
    for metric, keys in METRICS.items():
        found = False
        for pno, txt in pages_text:
            if section_pages and pno not in section_pages:
                continue
            for k in keys:
                rgx = kw_regex(k)
                start = 0
                while True:
                    m_k = rgx.search(txt, start)   # 原文本(保留换行, 数值不粘连)
                    if not m_k:
                        break
                    after = txt[m_k.end(): m_k.end() + 160]
                    val, raw = first_money(after)
                    if val is not None:
                        if os.environ.get("DBG"):
                            print(f"    [DBG] {metric} p{pno} k={k!r} raw={raw}")
                        res[metric] = (val, raw, pno)
                        found = True
                        break
                    start = m_k.end()
                if found:
                    break
            if found:          # 命中即停, 取最先命中的主表值(避免被后续分季度表覆盖)
                break
        if not found:
            res[metric] = (None, None, None)
    return res

def locate_section(pages_text, *keywords):
    pages = set()
    for pno, txt in pages_text:
        for kw in keywords:
            if kw in txt:
                pages.update({pno, min(pno + 1, len(pages_text)), min(pno + 2, len(pages_text))})
                break
    return pages

# 正文标题反推目录(兜底): 抓 "第X节" + 下一行标题; 跳过目录页(一页内出现>3个章节标题的页)
SEC_RE = re.compile(r"^第[一二三四五六七八九十百零]+节")
def derive_toc(pages_text):
    # 先统计每页章节标题数, 用于识别目录页
    per_page = {}
    for pno, txt in pages_text:
        c = sum(1 for ln in txt.splitlines() if SEC_RE.match(ln.strip()))
        if c:
            per_page[pno] = c
    toc = []
    seen = set()
    for pno, txt in pages_text:
        if per_page.get(pno, 0) > 3:   # 目录页: 跳过
            continue
        lines = txt.splitlines()
        for idx, line in enumerate(lines):
            s = line.strip()
            if not SEC_RE.match(s):
                continue
            nxt = ""
            for n in lines[idx + 1:]:
                if n.strip():
                    nxt = n.strip(); break
            title = (s + ((" " + nxt) if nxt else ""))[:34]
            key = s[:6]
            if key not in seen:
                seen.add(key)
                toc.append((title, pno))
    return toc

def parse_pdf(name, path):
    print(f"\n=== 解析: {name} ===")
    tracemalloc.start()
    t0 = time.time()
    doc = fitz.open(path)
    n_pages = doc.page_count
    total_chars = 0
    chunks = []
    for pno in range(n_pages):
        txt = doc.load_page(pno).get_text("text")
        total_chars += len(txt)
        chunks.append((pno + 1, txt))

    # 目录: 优先 get_toc, 垃圾则正文反推
    toc = []
    toc_source = "PDF书签(get_toc)"
    try:
        raw = doc.get_toc()
        junk = all(isinstance(t, list) and len(t) > 1 and str(t[1]).startswith("OLE_LINK") for t in raw) or len(raw) == 0
        if not junk:
            toc = [(t[1], t[2] + 1) for t in raw]
        else:
            toc = derive_toc(chunks)
            toc_source = "正文标题反推(兜底)"
    except Exception as e:
        toc = derive_toc(chunks)
        toc_source = "正文标题反推(兜底, get_toc异常:%s)" % e
    doc.close()
    elapsed = time.time() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    fsize = os.path.getsize(path)

    print(f"  文件大小 : {fsize/1024/1024:.2f} MB")
    print(f"  页数     : {n_pages}")
    print(f"  总字符数 : {total_chars:,}")
    print(f"  解析耗时 : {elapsed:.2f}s  ({n_pages/elapsed:.1f} 页/秒)")
    print(f"  Python内存峰值 : {peak/1024/1024:.1f} MB")
    print(f"  目录来源 : {toc_source}  ({len(toc)} 条)")
    if toc:
        for ttl, pg in toc[:8]:
            print(f"    - {ttl}  -> 第{pg}页")

    out = os.path.join(OUT_DIR, name + ".chunks.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"name": name, "pages": n_pages, "chunks": chunks}, f, ensure_ascii=False)

    if "年报" in name:
        sec = locate_section(chunks, "主要会计数据", "主要会计数据和财务指标")
        print(f"  指标章节页范围: {sorted(sec)}")
        m = find_metric(chunks, sec)
        print("  指标抽取:")
        for k, (val, raw, pg) in m.items():
            if val is not None:
                print(f"    {k}: {val:,.2f}  (原文={raw}, 第{pg}页)")
            else:
                print(f"    {k}: 未命中")
    return {"name": name, "pages": n_pages, "elapsed": elapsed, "peak_mb": peak/1024/1024,
            "toc": len(toc), "toc_source": toc_source, "chunks_file": out}

if __name__ == "__main__":
    summary = []
    for name, path in TARGETS:
        if not os.path.exists(path):
            print("缺失文件:", path); continue
        summary.append(parse_pdf(name, path))
    print("\n=== 压测结论 ===")
    for s in summary:
        ok = s["elapsed"] < 120 and s["peak_mb"] < 1024
        print(f"  {s['name']}: {s['pages']}页 / {s['elapsed']:.1f}s / 峰值{s['peak_mb']:.0f}MB / 目录{s['toc']}条({s['toc_source']}) -> {'PASS' if ok else 'FAIL'}")
