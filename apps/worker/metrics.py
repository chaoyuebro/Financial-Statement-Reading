"""指标抽取（技术方案 §6.5）。固化预研 #4 踩坑规则 → 单测。

三项指标（A 股财报口径）：
- revenue          营业收入 / 营业总收入           口径=合并
- net_profit_attr  归属于上市公司股东的净利润       口径=归母
- op_cash_flow     经营活动产生的现金流量净额       口径=合并

固化规则（预研踩坑，单测覆盖）：
1. 关键词匹配容忍词内空白（如「归属于上市公司股\\n东的净利润」）。
2. 数值抽取保留原始换行，不全局去空白（避免相邻数字粘连成巨数）。
3. parse_number 仅去千分位逗号、保留小数点（否则数值 ×100）。
4. 多表同名指标「命中即停」取最先出现的主表值（避免分季度表覆盖主要会计数据主表）。

口径/环比（§6.5 修正）：
- value_scope 统一 year_to_date（累计）；A 股季报为累计口径。
- MVP 不展示季报环比：qoq 恒置空；跨期单季推导放 P1。
- yoy 仅在主表同页含「上年同期/同期」数时计算，否则置空。
"""
from __future__ import annotations

import re

import db

# name -> 候选关键词 / 口径 / 单位
METRICS: dict[str, dict] = {
    "revenue": {
        "label": "营业收入",
        "keys": ["营业收入", "营业总收入"],
        "caliber": "合并",
        "unit": "元",
    },
    "net_profit_attr": {
        "label": "归属于上市公司股东的净利润",
        "keys": [
            "归属于上市公司股东的净利润",
            "归属于母公司股东的净利润",
            "归母净利润",
        ],
        "caliber": "归母",
        "unit": "元",
    },
    "op_cash_flow": {
        "label": "经营活动产生的现金流量净额",
        "keys": [
            "经营活动产生的现金流量净额",
            "经营活动产生的现金流",
            "经营活动现金净额",
        ],
        "caliber": "合并",
        "unit": "元",
    },
}

# 货币数字：千分位分组，或 6+ 位纯数字（带可选小数点）；允许括号/负号表示负数
MONEY_RE = re.compile(
    r"\(?-?[\d,]{1,3}(?:,\d{3})+(?:\.\d+)?\)?|-?[\d,]{6,}(?:\.\d+)?"
)
YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
KW_CACHE: dict[str, "re.Pattern[str]"] = {}


def kw_regex(k: str) -> "re.Pattern[str]":
    """关键词正则：在字符间允许任意空白（含换行），实现「词内空白容忍」。"""
    if k not in KW_CACHE:
        KW_CACHE[k] = re.compile(r"\s*".join(re.escape(c) for c in k))
    return KW_CACHE[k]


def parse_number(s: str) -> float | None:
    """仅去千分位逗号、保留小数点；括号/负号表示负数（规则 3）。"""
    s = s.strip()
    parenthesized = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").replace("−", "-")
    try:
        value = float(s)
        return -abs(value) if parenthesized else value
    except Exception:
        return None


def _first_money(s: str):
    """在 s 中取第一个货币数字，跳过纯年份（避免把年份当数值）。返回 (value, raw)。"""
    for m in MONEY_RE.finditer(s):
        tok = m.group(0)
        digits = re.sub(r"[^\d]", "", tok)
        if YEAR_RE.match(digits):
            continue
        v = parse_number(tok)
        if v is not None:
            return v, tok
    return None, None


def _detect_prev(txt: str, from_pos: int, window: int) -> float | None:
    """在关键词后 window 内查「上年同期/同期/去年同期」，取其后的货币数为上年值。"""
    seg = txt[from_pos : from_pos + window]
    m = re.search(r"(?:上年同期|去年同期|同期)", seg)
    if not m:
        return None
    prev, _ = _first_money(seg[m.end() :])
    return prev


def _second_money(s: str) -> float | None:
    """取片段内第二个货币数值，适配财报横向表格的“本期、上期、同比”列。"""
    values: list[float] = []
    for m in MONEY_RE.finditer(s):
        tok = m.group(0)
        digits = re.sub(r"[^\d]", "", tok)
        if YEAR_RE.match(digits):
            continue
        value = parse_number(tok)
        if value is not None:
            values.append(value)
        if len(values) == 2:
            return values[1]
    return None


def _nth_money(s: str, index: int) -> tuple[float | None, str | None]:
    """取片段内第 index 个货币数值（0-based），用于三季报区分单季值与累计值。"""
    values: list[tuple[float, str]] = []
    for m in MONEY_RE.finditer(s):
        tok = m.group(0)
        digits = re.sub(r"[^\d]", "", tok)
        if YEAR_RE.match(digits):
            continue
        value = parse_number(tok)
        if value is not None:
            values.append((value, tok))
        if len(values) > index:
            return values[index]
    return None, None


def _extract_one(
    pages_text: list[tuple[int, str]],
    keys: list[str],
    window: int = 160,
    value_index: int = 0,
):
    """按 4 坑规则抽取单指标；「命中即停」（规则 4）。返回 (value, raw, page, prev)。"""
    for pno, txt in pages_text:
        for k in keys:
            rgx = kw_regex(k)
            start = 0
            while True:
                m_k = rgx.search(txt, start)
                if not m_k:
                    break
                after = txt[m_k.end() : m_k.end() + window]
                effective_index = value_index
                if value_index > 0:
                    first_match = MONEY_RE.search(after)
                    before_first = after[: first_match.start()] if first_match else after
                    if "不适用" in before_first:
                        effective_index = 0
                val, raw = _nth_money(after, effective_index)
                if val is not None:
                    if effective_index > 0:
                        return val, raw, pno, None
                    # 标准年报表格通常按“本期、上期、同比”排列，表头中的
                    # “上年同期”可能位于关键词之前，不能只向后找文字标签。
                    prev = _second_money(after)
                    if prev is None:
                        prev = _detect_prev(txt, m_k.end(), window)
                    # 部分报表在本期、上年同期两列后明确标注“同比不适用”
                    # （常见于上期为负、本期转正）。此时不得自行强算百分比。
                    money = list(MONEY_RE.finditer(after))
                    if len(money) >= 2:
                        after_prev = after[money[1].end() : money[1].end() + 40]
                        if "不适用" in after_prev:
                            prev = None
                    return val, raw, pno, prev
                start = m_k.end()
    return None, None, None, None


def extract_metrics(
    pages_text: list[tuple[int, str]],
    period_type: str = "annual",
    value_scope: str = "year_to_date",
) -> list[dict]:
    """纯逻辑抽取（可在沙箱单测）。返回 metrics 表行（不含 id）。"""
    out: list[dict] = []
    for name, spec in METRICS.items():
        # 三季报先列本季度单季值、再列年初至报告期末累计值；MVP 指标统一累计口径。
        value_index = 1 if period_type == "q3" else 0
        val, _raw, page, prev = _extract_one(
            pages_text, spec["keys"], value_index=value_index
        )
        if val is None and value_index > 0:
            # 经营现金流等项目的“本报告期”列可能为“不适用”，累计值是首个货币数。
            val, _raw, page, prev = _extract_one(
                pages_text, spec["keys"], value_index=0
            )
        if val is None:
            continue
        yoy = None
        if prev not in (None, 0):
            yoy = round((val - prev) / abs(prev) * 100.0, 2)
        out.append(
            {
                "name": name,
                "source_value": val,
                "value": val,
                "derived_value": None,
                "calculation_formula": None,
                "is_derived": False,
                "period_type": period_type,
                "value_scope": value_scope,
                "unit": spec["unit"],
                "yoy": yoy,
                "qoq": None,  # MVP 季报不展示环比（§6.5）
                "page": page,
                "caliber": spec["caliber"],
                "confidence": 0.9,
            }
        )
    return out


def run_metrics(report_id: str, source: str, payload: dict | None = None) -> dict:
    """阶段入口：读 chunks → 还原每页文本 → 抽取 → 幂等写 metrics。"""
    payload = payload or {}
    version_tag = payload.get("version_tag") or db.version_tag_for(report_id, source)
    period_type = payload.get("period_type") or db.period_type_for(report_id) or "annual"

    chunks = db.read_chunks(report_id, version_tag)
    # 按 page 聚合 seq，按 seq 排序后拼接，还原「保留换行」的原页面文本
    by_page: dict[int, list[tuple[int, str]]] = {}
    for page, seq, text in chunks:
        by_page.setdefault(page, []).append((seq, text))
    pages_text: list[tuple[int, str]] = []
    for page in sorted(by_page):
        joined = "\n".join(t for _, t in sorted(by_page[page]))
        pages_text.append((page, joined))

    rows = extract_metrics(pages_text, period_type=period_type)
    n = db.write_metrics(report_id, version_tag, rows)
    return {"metrics": n, "rows": rows}
