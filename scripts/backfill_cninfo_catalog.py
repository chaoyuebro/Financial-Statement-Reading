"""按季度、可断点续跑地回填巨潮全历史报告目录（只写元数据，不下载 PDF）。"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import subprocess
import sys
from datetime import date

import psycopg2  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回填巨潮全历史报告目录")
    parser.add_argument("--start-year", type=int, default=1992)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    parser.add_argument("--max-pages", type=int, default=600)
    parser.add_argument("--delay", type=float, default=0.02)
    parser.add_argument("--force", action="store_true", help="重新执行已完成窗口")
    return parser.parse_args()


def quarter_windows(start_year: int, end_year: int):
    for year in range(start_year, end_year + 1):
        for start_month in (1, 4, 7, 10):
            end_month = start_month + 2
            yield (
                date(year, start_month, 1),
                date(year, end_month, calendar.monthrange(year, end_month)[1]),
            )


def mark(conn, start: date, end: date, status: str, **values) -> None:
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO catalog_sync_windows
                  (kind,date_from,date_to,status,seen,synced,error,started_at,completed_at,updated_at)
                VALUES
                  ('periodic',%s,%s,%s,%s,%s,%s,
                   CASE WHEN %s='running' THEN now() ELSE NULL END,
                   CASE WHEN %s='done' THEN now() ELSE NULL END,
                   now())
                ON CONFLICT (kind,date_from,date_to) DO UPDATE SET
                  status=EXCLUDED.status,
                  seen=EXCLUDED.seen,
                  synced=EXCLUDED.synced,
                  error=EXCLUDED.error,
                  started_at=CASE WHEN EXCLUDED.status='running' THEN now()
                                  ELSE catalog_sync_windows.started_at END,
                  completed_at=CASE WHEN EXCLUDED.status='done' THEN now()
                                    ELSE catalog_sync_windows.completed_at END,
                  updated_at=now()
                """,
                (
                    start,
                    end,
                    status,
                    int(values.get("seen") or 0),
                    int(values.get("synced") or 0),
                    values.get("error"),
                    status,
                    status,
                ),
            )


def main() -> int:
    args = parse_args()
    dsn = os.getenv("DATABASE_URL", "postgresql://fr:fr_dev_pw@127.0.0.1:5432/fr")
    conn = psycopg2.connect(dsn)

    for start, end in quarter_windows(args.start_year, args.end_year):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM catalog_sync_windows "
                "WHERE kind='periodic' AND date_from=%s AND date_to=%s",
                (start, end),
            )
            row = cur.fetchone()
        if row and row[0] == "done" and not args.force:
            print(json.dumps({"skip": True, "date_from": str(start), "date_to": str(end)}))
            continue

        mark(conn, start, end, "running")
        command = [
            sys.executable,
            "/app/scripts/sync_cninfo_reports.py",
            "--date-from",
            start.isoformat(),
            "--date-to",
            end.isoformat(),
            "--max-pages",
            str(args.max_pages),
            "--page-size",
            "30",
            "--delay",
            str(args.delay),
            "--kind",
            "periodic",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        try:
            summary = json.loads(lines[-1]) if lines else {}
        except json.JSONDecodeError:
            summary = {}
        if completed.returncode != 0:
            error = (completed.stderr or completed.stdout or "unknown error")[-2000:]
            mark(conn, start, end, "failed", error=error)
            print(error, file=sys.stderr)
            conn.close()
            return completed.returncode

        mark(
            conn,
            start,
            end,
            "done",
            seen=summary.get("seen"),
            synced=summary.get("synced"),
        )
        print(
            json.dumps(
                {
                    "done": True,
                    "date_from": str(start),
                    "date_to": str(end),
                    "seen": summary.get("seen", 0),
                    "synced": summary.get("synced", 0),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

