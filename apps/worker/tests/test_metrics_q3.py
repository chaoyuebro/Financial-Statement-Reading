import sys

sys.path.insert(0, "apps/worker")
import metrics  # noqa: E402


def test_q3_uses_year_to_date_value_not_single_quarter():
    text = """
营业收入
39,064,353,239.02
0.56
128,453,707,655.86
6.36
归属于上市公司股东的净利润
19,223,784,414.08
0.48
64,626,746,712.18
6.25
经营活动产生的现金流量净额
不适用
不适用
38,196,802,155.27
-14.01
"""
    rows = {
        row["name"]: row
        for row in metrics.extract_metrics([(1, text)], period_type="q3")
    }
    assert rows["revenue"]["value"] == 128_453_707_655.86
    assert rows["net_profit_attr"]["value"] == 64_626_746_712.18
    # 经营现金流前两列为“不适用”，其首个货币数本身就是累计值，仍应能提取。
    assert rows["op_cash_flow"]["value"] == 38_196_802_155.27


if __name__ == "__main__":
    test_q3_uses_year_to_date_value_not_single_quarter()
    print("PASS test_q3_uses_year_to_date_value_not_single_quarter")
