"""同步巨潮全市场定期报告及招股说明书元数据，供首页按披露时间倒序展示。

只同步公告元数据和官方 PDF 地址，不在同步过程中批量解析 PDF。
示例：
python scripts/sync_cninfo_reports.py --date-from 2026-01-01 --date-to 2026-07-19 --max-pages 40
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import psycopg2  # type: ignore

QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
PDF_BASE = "https://static.cninfo.com.cn/"
CATEGORIES_PERIODIC = ";".join(
    [
        "category_ndbg_szsh",
        "category_bndbg_szsh",
        "category_yjdbg_szsh",
        "category_sjdbg_szsh",
    ]
)
CATEGORY_PROSPECTUS = "category_sf_szsh"

PERIOD_PATTERNS = [
    (re.compile(r"((?:19|20)\d{2})年年度报告"), "annual", lambda y: y),
    (re.compile(r"((?:19|20)\d{2})年半年度报告"), "halfyear", lambda y: f"{y}H1"),
    (
        re.compile(r"((?:19|20)\d{2})年(?:第一季度|一季度)报告"),
        "quarterly",
        lambda y: f"{y}Q1",
    ),
    (
        re.compile(r"((?:19|20)\d{2})年(?:第三季度|三季度)报告"),
        "quarterly",
        lambda y: f"{y}Q3",
    ),
]
EXCLUDED_TITLES = (
    "摘要",
    "英文",
    "English",
    "提示性公告",
    "更正公告",
    "附录",
)
PROSPECTUS_PATTERN = re.compile(r"招股说明书")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步巨潮定期报告元数据")
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--page-size", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument(
        "--kind",
        choices=("periodic", "prospectus"),
        default="periodic",
        help="同步定期报告或招股说明书",
    )
    parser.add_argument(
        "--stock",
        default="",
        help="可选，巨潮股票参数，格式为“代码,orgId”",
    )
    return parser.parse_args()


def classify(title: str) -> tuple[str, str] | None:
    clean = re.sub(r"<[^>]+>", "", title).replace(" ", "")
    if any(term.lower() in clean.lower() for term in EXCLUDED_TITLES):
        return None
    if PROSPECTUS_PATTERN.search(clean):
        return "prospectus", "IPO"
    for pattern, report_type, period_fn in PERIOD_PATTERNS:
        match = pattern.search(clean)
        if match:
            return report_type, period_fn(match.group(1))
    return None


def exchange_for(code: str, page_column: str | None) -> str:
    column = (page_column or "").upper()
    if column.startswith("SH") or column == "KCB":
        return "sh"
    if "BSE" in column or code.startswith(("8", "4", "92")):
        return "bse"
    return "sz"


def refresh_current_version(cur, report_id: str) -> None:
    """按披露时间与修订优先级选择当前阅读版本。"""
    cur.execute(
        "UPDATE disclosures SET is_primary_source=false, is_current_version=false "
        "WHERE report_id=%s",
        (report_id,),
    )
    cur.execute(
        """
        SELECT source, source_announcement_id
        FROM disclosures
        WHERE report_id=%s
        ORDER BY
          disclosure_time DESC NULLS LAST,
          (
            COALESCE(title, '') LIKE '%%更正后%%'
            OR COALESCE(title, '') LIKE '%%更正版%%'
            OR COALESCE(title, '') LIKE '%%修订后%%'
            OR COALESCE(title, '') LIKE '%%修订版%%'
          ) DESC,
          source_announcement_id DESC
        LIMIT 1
        """,
        (report_id,),
    )
    selected = cur.fetchone()
    if not selected:
        return
    cur.execute(
        """
        UPDATE disclosures
        SET is_primary_source=true, is_current_version=true
        WHERE source=%s AND source_announcement_id=%s
        """,
        selected,
    )
    cur.execute(
        """
        UPDATE reports r
        SET title=d.title,
            disclosure_date=d.disclosure_date,
            disclosure_time=d.disclosure_time,
            primary_source=d.source
        FROM disclosures d
        WHERE r.id=%s
          AND d.source=%s
          AND d.source_announcement_id=%s
        """,
        (report_id, *selected),
    )


def fetch_page(args: argparse.Namespace, page: int) -> dict:
    payload = urllib.parse.urlencode(
        {
            "pageNum": str(page),
            "pageSize": str(args.page_size),
            "column": "szse",
            "tabName": "fulltext",
            "plate": "",
            "stock": args.stock,
            "searchkey": "招股说明书" if args.kind == "prospectus" else "",
            "secid": "",
            "category": (
                CATEGORY_PROSPECTUS
                if args.kind == "prospectus"
                else CATEGORIES_PERIODIC
            ),
            "trade": "",
            "seDate": f"{args.date_from}~{args.date_to}",
            "sortName": "time",
            "sortType": "desc",
            "isHLtitle": "true",
        }
    ).encode()
    request = urllib.request.Request(
        QUERY_URL,
        data=payload,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
            "Origin": "https://www.cninfo.com.cn",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
    )
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in (408, 429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
        time.sleep(min(8.0, 0.8 * (2**attempt)))
    assert last_error is not None
    raise last_error


def upsert_announcement(cur, item: dict) -> bool:
    title = re.sub(r"<[^>]+>", "", item.get("announcementTitle") or "").strip()
    classified = classify(title)
    if not classified:
        return False
    report_type, period = classified
    code = str(item.get("secCode") or "").strip()
    announcement_id = str(item.get("announcementId") or "").strip()
    adjunct = str(item.get("adjunctUrl") or "").lstrip("/")
    if not (code and announcement_id and adjunct):
        return False

    short_name = str(item.get("secName") or code).strip()
    exchange = exchange_for(code, item.get("pageColumn"))
    disclosure_time = datetime.fromtimestamp(
        int(item["announcementTime"]) / 1000, tz=ZoneInfo("Asia/Shanghai")
    )
    disclosed = disclosure_time.date()
    canonical_key = f"{code}:{report_type}:{period}"
    pdf_url = urllib.parse.urljoin(PDF_BASE, adjunct)

    cur.execute(
        """
        INSERT INTO companies (code, name, short_name, org_id, exchange)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (code) DO UPDATE SET
          short_name=EXCLUDED.short_name,
          org_id=COALESCE(EXCLUDED.org_id, companies.org_id),
          exchange=EXCLUDED.exchange
        """,
        (code, short_name, short_name, item.get("orgId"), exchange),
    )
    cur.execute("SELECT id::text FROM reports WHERE canonical_key=%s", (canonical_key,))
    existing = cur.fetchone()
    report_id = existing[0] if existing else str(uuid.uuid4())
    if existing:
        cur.execute(
            """
            UPDATE reports SET
              title=CASE WHEN disclosure_date IS NULL OR disclosure_date <= %s THEN %s ELSE title END,
              disclosure_date=GREATEST(disclosure_date, %s),
              disclosure_time=GREATEST(disclosure_time, %s),
              primary_source='cninfo'
            WHERE id=%s
            """,
            (disclosed, title, disclosed, disclosure_time, report_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO reports
              (id,company_code,type,report_period,canonical_key,title,
               disclosure_date,disclosure_time,primary_source,status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'cninfo','pending')
            """,
            (
                report_id,
                code,
                report_type,
                period,
                canonical_key,
                title,
                disclosed,
                disclosure_time,
            ),
        )

    cur.execute(
        "SELECT report_id::text FROM disclosures WHERE source='cninfo' AND source_announcement_id=%s",
        (announcement_id,),
    )
    known = cur.fetchone()
    if known and known[0] == report_id:
        cur.execute(
            """
            UPDATE disclosures SET title=%s, disclosure_date=%s, disclosure_time=%s, pdf_url=%s,
              adjunct_url=%s
            WHERE source='cninfo' AND source_announcement_id=%s
            """,
            (title, disclosed, disclosure_time, pdf_url, adjunct, announcement_id),
        )
        refresh_current_version(cur, report_id)
        return True

    cur.execute(
        """
        INSERT INTO disclosures
          (source,source_announcement_id,report_id,company_code,type,report_period,
           title,disclosure_date,disclosure_time,pdf_url,adjunct_url,is_primary_source,is_current_version)
        VALUES ('cninfo',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,false)
        ON CONFLICT (source,source_announcement_id) DO UPDATE SET
          report_id=EXCLUDED.report_id,
          company_code=EXCLUDED.company_code,
          type=EXCLUDED.type,
          report_period=EXCLUDED.report_period,
          title=EXCLUDED.title,
          disclosure_date=EXCLUDED.disclosure_date,
          disclosure_time=EXCLUDED.disclosure_time,
          pdf_url=EXCLUDED.pdf_url,
          adjunct_url=EXCLUDED.adjunct_url,
          is_primary_source=false,
          is_current_version=false
        """,
        (
            announcement_id,
            report_id,
            code,
            report_type,
            period,
            title,
            disclosed,
            disclosure_time,
            pdf_url,
            adjunct,
        ),
    )
    refresh_current_version(cur, report_id)
    return True


def main() -> int:
    args = parse_args()
    dsn = os.getenv(
        "DATABASE_URL", "postgresql://fr:fr_dev_pw@127.0.0.1:5432/fr"
    )
    conn = psycopg2.connect(dsn)
    seen = 0
    synced = 0
    for page in range(1, args.max_pages + 1):
        data = fetch_page(args, page)
        announcements = data.get("announcements") or []
        if not announcements:
            break
        with conn:
            with conn.cursor() as cur:
                for item in announcements:
                    seen += 1
                    if upsert_announcement(cur, item):
                        synced += 1
        print(
            json.dumps(
                {
                    "page": page,
                    "fetched": len(announcements),
                    "seen": seen,
                    "synced": synced,
                    "total": data.get("totalAnnouncement"),
                },
                ensure_ascii=False,
            )
        )
        total = int(data.get("totalAnnouncement") or 0)
        if len(announcements) < args.page_size or (total and page * args.page_size >= total):
            break
        time.sleep(args.delay)
    conn.close()
    print(json.dumps({"done": True, "seen": seen, "synced": synced}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
