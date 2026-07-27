"""为 W5-6 e2e 准备一份「最小可跑」的真实报告（按真实 schema）。
- companies(code PK)
- reports(id, company_code, status, ...)
- disclosures(source, source_announcement_id, PK composite)
- document_chunks(report_id, page, seq, text, version_tag)
- metrics(report_id, name, value, page, period_type, ...)

仅用于本地 docker e2e 验证，使用确定性 canonical_key。
"""
import json
import os
import sys
import uuid

import psycopg2  # type: ignore

DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://fr:fr_dev_pw@127.0.0.1:5432/fr",
)
COMPANY_CODE = "600519"
REPORT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
DISC_SOURCE = "cninfo"
DISC_ANN_ID = "ann-seed-001"
CANONICAL_KEY = f"{COMPANY_CODE}:annual:2022"


def main() -> int:
    conn = psycopg2.connect(DSN)
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companies (code, name, short_name, exchange)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
                """,
                (COMPANY_CODE, "贵州茅台", "茅台", "SH"),
            )
            # 清理旧版脚本曾写入的错误规范键 annual:2022，避免首页产生重复报告。
            cur.execute(
                "SELECT id::text FROM reports WHERE id=%s AND canonical_key <> %s",
                (str(REPORT_ID), CANONICAL_KEY),
            )
            legacy = cur.fetchone()
            if legacy:
                cur.execute("DELETE FROM metrics WHERE report_id = %s", (legacy[0],))
                cur.execute("DELETE FROM document_chunks WHERE report_id = %s", (legacy[0],))
                cur.execute("DELETE FROM parse_jobs WHERE report_id = %s", (legacy[0],))
                cur.execute("DELETE FROM disclosures WHERE report_id = %s", (legacy[0],))
                cur.execute("DELETE FROM reports WHERE id = %s", (legacy[0],))

            # 优先复用跨源归并后的规范报告，绝不为同一 company/type/period 再建一行。
            cur.execute(
                "SELECT id::text FROM reports WHERE canonical_key=%s",
                (CANONICAL_KEY,),
            )
            existing = cur.fetchone()
            report_id = existing[0] if existing else str(REPORT_ID)
            if not existing:
                cur.execute(
                    """
                    INSERT INTO reports
                      (id, company_code, type, report_period, canonical_key,
                       report_period_unknown, title, disclosure_date, status, is_withdrawn)
                    VALUES
                      (%s, %s, 'annual', '2022', %s, false,
                       '贵州茅台2022年年度报告', '2023-03-31', 'metrics_done', false)
                    """,
                    (report_id, COMPANY_CODE, CANONICAL_KEY),
                )
            else:
                cur.execute("UPDATE reports SET status='metrics_done' WHERE id=%s", (report_id,))

            cur.execute("DELETE FROM metrics WHERE report_id = %s", (report_id,))
            cur.execute("DELETE FROM document_chunks WHERE report_id = %s", (report_id,))

            toc = [
                {"page": 1, "title": "第一节 重要提示"},
                {"page": 2, "title": "第二节 公司概况"},
                {"page": 3, "title": "第三节 会计数据"},
            ]
            cur.execute("SELECT 1 FROM disclosures WHERE report_id=%s LIMIT 1", (report_id,))
            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO disclosures
                      (source, source_announcement_id, report_id, company_code, type,
                       report_period, report_period_unknown, title, disclosure_date,
                       is_primary_source, is_current_version, toc)
                    VALUES
                      (%s, %s, %s, %s, 'annual', '2022', false,
                       '贵州茅台2022年年度报告', '2023-03-31', true, true, %s::jsonb)
                    """,
                    (DISC_SOURCE, DISC_ANN_ID, report_id, COMPANY_CODE, json.dumps(toc)),
                )

            chunks = [
                (1, 1, "重要提示：本公司董事会及全体董事保证本报告内容真实、准确、完整。"),
                (3, 1, "一、营业收入 124,100,000,000.00 元（合并报表口径），同比 16.87%。"),
                (3, 2, "二、归属于上市公司股东的净利润 58,200,000,000.00 元，同比 19.55%。"),
                (3, 3, "三、经营活动产生的现金流量净额 36,600,000,000.00 元。"),
            ]
            for page, seq, text in chunks:
                cur.execute(
                    """INSERT INTO document_chunks
                         (report_id, page, seq, text, version_tag)
                       VALUES (%s, %s, %s, %s, 'v1')""",
                    (report_id, page, seq, text),
                )

            metrics = [
                ("revenue", 124_100_000_000.0, False, "year", "year_to_date", "元", 16.87, None, 3, "合并", 0.97),
                ("net_profit_attr", 58_200_000_000.0, False, "year", "year_to_date", "元", 19.55, None, 3, "归母", 0.96),
                ("op_cash_flow", 36_600_000_000.0, False, "year", "year_to_date", "元", None, None, 3, "合并", 0.94),
            ]
            for (name, val, is_derived, period_type, scope, unit, yoy, qoq, page, caliber, conf) in metrics:
                cur.execute(
                    """INSERT INTO metrics
                         (report_id, version_tag, name, value, is_derived,
                          period_type, value_scope, unit, yoy, qoq, page, caliber, confidence)
                       VALUES (%s,'v1',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (report_id, name, val, is_derived, period_type, scope, unit, yoy, qoq, page, caliber, conf),
                )

    print(f"[ok] 种子完成 report_id={report_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
