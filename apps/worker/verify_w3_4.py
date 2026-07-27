"""W3-4 端到端验证（需在本地 Postgres + Worker 依赖环境运行）。

运行前提：
    export PYTHONPATH=/repo/apps          # 注意：放 apps 而非 apps/worker，
                                           # 这样 worker 才是 apps/worker 包（import worker.config 正确）
    pip install -r apps/worker/requirements.txt -r apps/worker/requirements-parse.txt
    # DATABASE_URL 指向可达的 Postgres（默认 postgresql://fr:fr_dev_pw@localhost:5432/fr）
    # Redis 仅异步 RQ 路径需要；本脚本走同步直跑，不依赖 Redis

运行（在仓库根目录执行）：
    python -m worker.verify_w3_4

验证内容：
    1. PyMuPDF 生成种子 PDF（含书签目录 + 正文）。
    2. 写入 reports + disclosures 种子行（cninfo 主源；pdf_url 占位，用 local_pdf_path 直读）。
    3. 同步执行 download.run_download → parse.run_parse（跳过 RQ，直接验证 DB 写入）。
    4. 断言 document_chunks 行数 > 0、disclosures.toc 非空、reports.status='parsed'。
    5. 幂等：重复 run_parse，断言 document_chunks 行数稳定（先删旧再写）。
    6. parse_jobs 幂等：ensure_parse_job 两次，第二次 created=False。
    7. 主源切换：构造主源失败场景，验证 switch_primary_source 翻转。
脚本结束清理种子数据（按生成的 report_id 删除），不污染既有库。
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz  # noqa: F401 — 确保 PyMuPDF 可用

import config  # noqa: F401
import db
import download
import parse


def _make_seed_pdf(path: str) -> None:
    doc = fitz.open()
    doc.new_page().insert_text((50, 50), "Table of Contents\nSection A\nSection B\nSection C")
    doc.new_page().insert_text(
        (50, 50),
        "Section A: Revenue\n" + ("The company reported revenue of 1,234,567 in the period. " * 30),
    )
    doc.new_page().insert_text(
        (50, 50),
        "Section B: Profit\n" + ("Net profit attributable to shareholders was 234,567. " * 30),
    )
    doc.set_toc([(1, "Section A: Revenue", 1), (1, "Section B: Profit", 2)])
    doc.save(path)
    doc.close()


def _seed_rows(report_id: str, source_ann_id: str) -> None:
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO reports
                   (id, company_code, type, report_period, canonical_key, title, disclosure_date, status, primary_source)
                   VALUES (%s,'600519','annual','2099',%s,'验证报告','2099-04-01','pending','cninfo')""",
                (report_id, f"600519:annual:{source_ann_id}"),
            )
            cur.execute(
                """INSERT INTO disclosures
                   (source, source_announcement_id, report_id, type, pdf_url, is_primary_source, is_current_version)
                   VALUES ('cninfo',%s,%s,'annual','http://static.cninfo.com.cn/seed.pdf',true,true)""",
                (source_ann_id, report_id),
            )
            cur.execute(
                """INSERT INTO disclosures
                   (source, source_announcement_id, report_id, type, pdf_url, is_primary_source, is_current_version)
                   VALUES ('eastmoney',%s,%s,'annual','http://pdf.dfcfw.com/seed.pdf',false,false)""",
                (source_ann_id + "-em", report_id),
            )
        conn.commit()
    finally:
        db.put_conn(conn)


def _cleanup(report_id: str) -> None:
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            # document_chunks 通过 version_tag 关联；直接按 report_id 删除
            cur.execute("DELETE FROM document_chunks WHERE report_id=%s", (report_id,))
            cur.execute("DELETE FROM parse_jobs WHERE report_id=%s", (report_id,))
            cur.execute("DELETE FROM disclosures WHERE report_id=%s", (report_id,))
            cur.execute("DELETE FROM reports WHERE id=%s", (report_id,))
        conn.commit()
    finally:
        db.put_conn(conn)


def _count_chunks(report_id: str, version_tag: str) -> int:
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM document_chunks WHERE report_id=%s AND version_tag=%s",
                (report_id, version_tag),
            )
            return cur.fetchone()[0]
    finally:
        db.put_conn(conn)


def _report_status(report_id: str) -> str | None:
    m = db.report_meta(report_id)
    return m.get("status") if m else None


def _toc_of(report_id: str, source: str):
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT toc FROM disclosures WHERE report_id=%s AND source=%s",
                (report_id, source),
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        db.put_conn(conn)


def main() -> int:
    report_id = str(uuid.uuid4())
    ann_id = "SEED" + report_id[:8]
    print(f"[verify] report_id={report_id}")
    failures = 0

    with tempfile.TemporaryDirectory() as d:
        pdf = os.path.join(d, "seed.pdf")
        _make_seed_pdf(pdf)
        _seed_rows(report_id, ann_id)

        try:
            # 3) download（local_pdf_path 直读，跳过网络/SSRF）
            dl = download.run_download(report_id, "cninfo", {"local_pdf_path": pdf})
            print(f"[verify] download -> {dl['source']} size={dl['size']} path={dl['pdf_path']}")

            # 4) parse
            pr = parse.run_parse(
                report_id, dl["source"], {"pdf_path": dl["pdf_path"]}
            )
            print(f"[verify] parse -> pages={pr['n_pages']} chunks={pr['n_chunks']} toc={pr['n_toc']} src={pr['toc_source']}")

            version_tag = db.version_tag_for(report_id, dl["source"])
            n_chunks = _count_chunks(report_id, version_tag)
            toc = _toc_of(report_id, dl["source"])
            status = _report_status(report_id)

            ok = True
            if n_chunks <= 0:
                print("[FAIL] document_chunks 无数据"); ok = False
            if not toc:
                print("[FAIL] disclosures.toc 为空"); ok = False
            if status != "parsed":
                print(f"[FAIL] reports.status={status} (期望 parsed)"); ok = False
            print(f"[verify] chunks={n_chunks} toc_entries={len(toc)} status={status}")
            if not ok:
                failures += 1

            # 5) 幂等：重复 parse，行数应稳定（先删旧再写）
            pr2 = parse.run_parse(report_id, dl["source"], {"pdf_path": dl["pdf_path"]})
            n_chunks2 = _count_chunks(report_id, version_tag)
            if n_chunks2 != pr2["n_chunks"]:
                print(f"[FAIL] 幂等失败: 第一次 {n_chunks} 行, 第二次 {n_chunks2} 行")
                failures += 1
            else:
                print(f"[verify] 幂等 OK: 重复 parse 后仍为 {n_chunks2} 行")

            # 6) parse_jobs 幂等
            jid1, created1 = db.ensure_parse_job(report_id, "parse", "cninfo", {})
            jid2, created2 = db.ensure_parse_job(report_id, "parse", "cninfo", {})
            if created1 and created2:
                print("[FAIL] ensure_parse_job 第二次不应 created=True")
                failures += 1
            else:
                print(f"[verify] parse_jobs 幂等 OK: id={jid1} created1={created1} created2={created2}")

            # 7) 主源切换：模拟 cninfo 失败 → 翻转 eastmoney 为主源
            db.switch_primary_source(report_id, "eastmoney")
            if db.primary_source_for(report_id) != "eastmoney":
                print("[FAIL] switch_primary_source 未翻转")
                failures += 1
            else:
                print("[verify] switch_primary_source OK: primary=eastmoney")

        finally:
            _cleanup(report_id)

    print()
    if failures == 0:
        print("W3-4 端到端验证全部通过 ✅")
        return 0
    print(f"W3-4 验证存在 {failures} 项失败 ❌")
    return 1


if __name__ == "__main__":
    sys.exit(main())
