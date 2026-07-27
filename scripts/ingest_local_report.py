"""把本地 PDF 导入开发数据库，并执行下载、解析、指标抽取。

典型用法（在 worker 容器内）：
python /tmp/ingest_local_report.py \
  --pdf /tmp/report.pdf --code 600519 --name 贵州茅台酒股份有限公司 \
  --short-name 贵州茅台 --exchange sh --type annual --period 2025 \
  --title 贵州茅台酒股份有限公司2025年年度报告 \
  --disclosure-date 2026-03-31
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

import psycopg2  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入本地财报 PDF")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--code", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--short-name")
    parser.add_argument("--exchange", required=True, choices=("sh", "sz", "bse"))
    parser.add_argument(
        "--type",
        required=True,
        choices=("annual", "halfyear", "quarterly", "prospectus"),
    )
    parser.add_argument("--period", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--disclosure-date", required=True)
    parser.add_argument("--source", default="cninfo", choices=("cninfo", "eastmoney"))
    parser.add_argument("--announcement-id")
    parser.add_argument("--worker-path", default=os.getenv("WORKER_MODULE_PATH", "/app/apps/worker"))
    return parser.parse_args()


def prepare_record(args: argparse.Namespace) -> tuple[str, str]:
    pdf = Path(args.pdf).resolve()
    if not pdf.is_file():
        raise FileNotFoundError(f"PDF 不存在: {pdf}")

    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    announcement_id = args.announcement_id or f"local-{digest[:24]}"
    canonical_key = f"{args.code}:{args.type}:{args.period}"
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://fr:fr_dev_pw@127.0.0.1:5432/fr",
    )

    conn = psycopg2.connect(dsn)
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO companies (code, name, short_name, exchange)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                  name=EXCLUDED.name,
                  short_name=COALESCE(EXCLUDED.short_name, companies.short_name),
                  exchange=EXCLUDED.exchange
                """,
                (args.code, args.name, args.short_name, args.exchange),
            )
            cur.execute(
                "SELECT id::text FROM reports WHERE canonical_key=%s",
                (canonical_key,),
            )
            row = cur.fetchone()
            report_id = row[0] if row else str(uuid.uuid4())
            if row:
                cur.execute(
                    """
                    UPDATE reports SET title=%s, disclosure_date=%s, primary_source=%s,
                      status='pending', is_withdrawn=false
                    WHERE id=%s
                    """,
                    (args.title, args.disclosure_date, args.source, report_id),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO reports
                      (id, company_code, type, report_period, canonical_key,
                       title, disclosure_date, primary_source, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')
                    """,
                    (
                        report_id,
                        args.code,
                        args.type,
                        args.period,
                        canonical_key,
                        args.title,
                        args.disclosure_date,
                        args.source,
                    ),
                )

            # 一个规范报告只保留一个当前版本和一个主来源。
            cur.execute(
                """
                UPDATE disclosures SET is_primary_source=false, is_current_version=false
                WHERE report_id=%s
                """,
                (report_id,),
            )
            cur.execute(
                """
                INSERT INTO disclosures
                  (source, source_announcement_id, report_id, company_code, type,
                   report_period, title, disclosure_date, pdf_url,
                   is_primary_source, is_current_version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,true,true)
                ON CONFLICT (source, source_announcement_id) DO UPDATE SET
                  report_id=EXCLUDED.report_id,
                  company_code=EXCLUDED.company_code,
                  type=EXCLUDED.type,
                  report_period=EXCLUDED.report_period,
                  title=EXCLUDED.title,
                  disclosure_date=EXCLUDED.disclosure_date,
                  pdf_url=EXCLUDED.pdf_url,
                  is_primary_source=true,
                  is_current_version=true
                """,
                (
                    args.source,
                    announcement_id,
                    report_id,
                    args.code,
                    args.type,
                    args.period,
                    args.title,
                    args.disclosure_date,
                    f"file://{pdf}",
                ),
            )
    conn.close()
    return report_id, announcement_id


def run_stages(args: argparse.Namespace, report_id: str) -> dict:
    sys.path.insert(0, args.worker_path)
    import db  # type: ignore
    import download  # type: ignore
    import embed  # type: ignore
    import metrics  # type: ignore
    import parse  # type: ignore

    downloaded = download.run_download(
        report_id,
        args.source,
        {"local_pdf_path": str(Path(args.pdf).resolve())},
    )
    parsed = parse.run_parse(
        report_id,
        downloaded["source"],
        {"pdf_path": downloaded["pdf_path"]},
    )
    embedded = embed.run_embed(
        report_id,
        downloaded["source"],
        {"version_tag": downloaded["version_tag"]},
    )
    period_type = (
        "h1"
        if args.type == "halfyear"
        else ("q3" if args.type == "quarterly" and args.period.upper().endswith("Q3") else args.type)
    )
    extracted = metrics.run_metrics(
        report_id,
        downloaded["source"],
        {
            "version_tag": downloaded["version_tag"],
            "period_type": period_type,
        },
    )
    db.set_report_status(report_id, "ready")
    return {
        "download": {
            "bytes": downloaded["size"],
            "version_tag": downloaded["version_tag"],
        },
        "parse": parsed,
        "embed": embedded,
        "metrics": extracted,
    }


def main() -> int:
    args = parse_args()
    report_id, announcement_id = prepare_record(args)
    result = run_stages(args, report_id)
    print(
        json.dumps(
            {
                "report_id": report_id,
                "announcement_id": announcement_id,
                **result,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
