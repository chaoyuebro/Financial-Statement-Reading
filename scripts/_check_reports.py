"""Dump reports + metrics counts for debugging."""
import os
import psycopg2  # type: ignore

dsn = os.environ.get(
    "DATABASE_URL",
    "postgresql://fr:fr_dev_pw@127.0.0.1:5432/fr",
)
conn = psycopg2.connect(dsn)
with conn, conn.cursor() as cur:
    cur.execute("""
        SELECT r.id, r.status, c.name, r.report_period, r.type,
               (SELECT COUNT(*) FROM document_chunks WHERE report_id=r.id) AS chunks,
               (SELECT COUNT(*) FROM metrics WHERE report_id=r.id) AS metrics
        FROM reports r
        JOIN companies c ON c.code = r.company_code
        ORDER BY r.disclosure_date DESC NULLS LAST
        LIMIT 10
    """)
    for row in cur.fetchall():
        print(row)
