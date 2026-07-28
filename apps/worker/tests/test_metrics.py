"""指标抽取单测（纯逻辑，无需 DB / 重依赖）。

覆盖预研 4 坑 + 口径 + 同比 + 累计口径：
- 坑1 关键词词内空白容忍
- 坑2 相邻数字不粘连（保留换行）
- 坑3 parse_number 保留小数点
- 坑4 命中即停取最先主表值
- caliber：归母 / 合并
- yoy：主表同页含上年同期数时计算
- value_scope=year_to_date，qoq 恒空
"""
import sys

sys.path.insert(0, "apps/worker")
import metrics  # noqa: E402

PAGE1 = (
    "主要会计数据\n"
    "一、营业收入\n"
    "12,345,678,901.23\n"
    "其中：利息净收入 ...\n"
    "二、归属于上市公司股\n"
    "东的净利润\n"
    "5,678,901,234.56\n"
    "上年同期 5,000,000,000.00\n"
    "三、经营活动产生的现金流量净额\n"
    "2,345,678,901.12\n"
)
# 分季度表（同名指标，值不同）——用于验证「命中即停」取主表值
PAGE3 = (
    "第三季度主要会计数据\n"
    "营业收入\n"
    "9,999,999,999.99\n"
    "归属于上市公司股东的净利润\n"
    "1,111,111,111.11\n"
)


def _by_name(rows):
    return {r["name"]: r for r in rows}


def test_four_metrics_extracted():
    rows = metrics.extract_metrics([(1, PAGE1), (3, PAGE3)])
    names = {r["name"] for r in rows}
    assert names == {"revenue", "net_profit_attr", "op_cash_flow"}, names


def test_revenue_value_and_page():
    rows = _by_name(metrics.extract_metrics([(1, PAGE1), (3, PAGE3)]))
    r = rows["revenue"]
    assert r["value"] == 12345678901.23, r["value"]  # 坑3: 小数点保留(非 ×100)
    assert r["page"] == 1  # 坑4: 命中即停取主表(非分季度表)
    assert r["caliber"] == "合并"
    assert r["value_scope"] == "year_to_date"
    assert r["qoq"] is None


def test_net_profit_caliber_and_yoy():
    rows = _by_name(metrics.extract_metrics([(1, PAGE1)]))
    r = rows["net_profit_attr"]
    assert r["value"] == 5678901234.56
    assert r["caliber"] == "归母"
    assert r["page"] == 1
    assert r["yoy"] is not None
    exp = round((5678901234.56 - 5_000_000_000.0) / 5_000_000_000.0 * 100, 2)
    assert abs(r["yoy"] - exp) < 0.01, (r["yoy"], exp)


def test_op_cash_flow_no_yoy():
    rows = _by_name(metrics.extract_metrics([(1, PAGE1)]))
    r = rows["op_cash_flow"]
    assert r["value"] == 2345678901.12
    assert r["page"] == 1
    assert r["yoy"] is None
    assert r["qoq"] is None


def test_no_glue_adjacent_numbers():  # 坑2
    txt = "营业收入\n123\n456,789,012.34\n"
    rows = _by_name(metrics.extract_metrics([(1, txt)]))
    assert rows["revenue"]["value"] == 456789012.34, rows["revenue"]["value"]


def test_keyword_newline_tolerance():  # 坑1
    txt = "归属于上市公司股\n东的净利润\n1,234.56\n"
    rows = _by_name(metrics.extract_metrics([(1, txt)]))
    assert "net_profit_attr" in rows
    assert rows["net_profit_attr"]["value"] == 1234.56


def test_period_type_passthrough():
    rows = metrics.extract_metrics(
        [(1, PAGE1)], period_type="q3", value_scope="year_to_date"
    )
    assert all(r["period_type"] == "q3" for r in rows)
    assert all(r["value_scope"] == "year_to_date" for r in rows)


def test_negative_number_keeps_sign():
    assert metrics.parse_number("-72,807,436.73") == -72807436.73
    assert metrics.parse_number("(72,807,436.73)") == -72807436.73


def test_yoy_not_calculated_when_source_says_not_applicable():
    txt = (
        "归属于上市公司股东的净利润\n"
        "20,413,758.47\n"
        "-72,807,436.73\n"
        "不适用\n"
    )
    row = _by_name(metrics.extract_metrics([(5, txt)]))["net_profit_attr"]
    assert row["value"] == 20413758.47
    assert row["yoy"] is None


def test_structured_table_preferred_and_unit_converted():
    narrative = (
        "2025 年营业总收入4,585 亿元，归母净利润439.5 亿元。"
        "ToB业务收入1,228亿元，同比增长17.5%。"
    )
    table = (
        "营业收入（千元）\n456,451,731\n407,149,600\n12.11%\n"
        "归属于上市公司股东的净利润（千元）\n"
        "43,945,411\n38,537,237\n14.03%\n"
        "经营活动产生的现金流量净额（千元）\n"
        "53,345,930\n60,511,572\n-11.84%\n"
    )
    rows = _by_name(metrics.extract_metrics([(2, narrative), (9, table)]))
    assert rows["revenue"]["value"] == 456_451_731_000
    assert rows["revenue"]["page"] == 9
    assert rows["revenue"]["yoy"] == 12.11
    assert rows["net_profit_attr"]["value"] == 43_945_411_000
    assert rows["net_profit_attr"]["page"] == 9
    assert rows["op_cash_flow"]["value"] == 53_345_930_000
    assert rows["op_cash_flow"]["yoy"] == -11.84


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
