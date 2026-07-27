"""PostgreSQL 访问层（psycopg2）。

提供：披露源查询、报告级元信息守卫、parse_jobs 幂等写入、
document_chunks 事务写入（先删旧产物再写）、toc 回写、状态流转。

所有对外函数均为幂等友好：重复执行同一阶段结果一致（§5.2）。
"""
from __future__ import annotations

import json
from typing import Any

import psycopg2
import psycopg2.extras
import psycopg2.pool

import config

_pool: psycopg2.pool.SimpleConnectionPool | None = None


def get_conn() -> psycopg2.extensions.connection:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.SimpleConnectionPool(1, 4, config.DATABASE_URL)
    return _pool.getconn()


def put_conn(conn: psycopg2.extensions.connection) -> None:
    if _pool is not None:
        _pool.putconn(conn)


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def report_meta(report_id: str) -> dict | None:
    """返回报告级守卫信息；不存在返回 None。"""
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT report_period_unknown, is_withdrawn, status, primary_source "
                "FROM reports WHERE id=%s",
                (report_id,),
            )
            return cur.fetchone()
    finally:
        put_conn(conn)


def pdf_sources_for(report_id: str) -> list[dict]:
    """该报告的所有披露源（主源排前），供下载阶段主源失败回退备用源。"""
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT source, source_announcement_id, pdf_url, is_primary_source "
                "FROM disclosures WHERE report_id=%s "
                "ORDER BY is_primary_source DESC, created_at ASC",
                (report_id,),
            )
            return cur.fetchall()
    finally:
        put_conn(conn)


def primary_source_for(report_id: str) -> str | None:
    meta = report_meta(report_id)
    return meta["primary_source"] if meta else None


def period_type_for(report_id: str) -> str | None:
    """由 reports.report_period 推导期类型：2023→annual / 2023H1→h1 / 2023Q1→q1 / 2023Q3→q3。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT report_period FROM reports WHERE id=%s", (report_id,))
            row = cur.fetchone()
        if not row or not row[0]:
            return None
        rp = str(row[0])
        if rp.endswith("H1"):
            return "h1"
        if rp.endswith("Q1"):
            return "q1"
        if rp.endswith("Q3"):
            return "q3"
        return "annual"
    finally:
        put_conn(conn)


def version_tag_for(report_id: str, source: str) -> str:
    """产物版本标记 = disclosures 的 'source:source_announcement_id'（§4）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_announcement_id FROM disclosures "
                "WHERE report_id=%s AND source=%s",
                (report_id, source),
            )
            row = cur.fetchone()
        if not row:
            raise ValueError(f"无披露源 {source} for report {report_id}")
        return f"{source}:{row[0]}"
    finally:
        put_conn(conn)


def get_parse_job(job_id: str) -> dict | None:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM parse_jobs WHERE id=%s", (job_id,))
            return cur.fetchone()
    finally:
        put_conn(conn)


# ---------------------------------------------------------------------------
# parse_jobs 幂等写入（§5.1 / §5.2）
# ---------------------------------------------------------------------------
def ensure_parse_job(
    report_id: str, stage: str, source: str, payload: dict | None = None
) -> tuple[str, bool]:
    """幂等创建 parse_jobs。

    返回 (job_id, created)：created=False 表示该 report_id+stage 已有任务。
    job_id 即幂等键 = '{report_id}_{stage}'，同时满足 RQ 对任务 ID 字符集的限制。
    """
    job_id = f"{report_id}_{stage}"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO parse_jobs (id, report_id, source, stage, status, payload)
                   VALUES (%s, %s, %s, %s, 'pending', %s::jsonb)
                   ON CONFLICT (report_id, stage) DO NOTHING""",
                (
                    job_id,
                    report_id,
                    source,
                    stage,
                    json.dumps(payload) if payload is not None else None,
                ),
            )
            created = cur.rowcount > 0
            if not created:
                cur.execute(
                    "SELECT id FROM parse_jobs WHERE report_id=%s AND stage=%s",
                    (report_id, stage),
                )
                job_id = cur.fetchone()[0]
            conn.commit()
            return job_id, created
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def update_parse_job(
    job_id: str,
    status: str,
    error: str | None = None,
    lease_token: str | None = None,
    lease_expires_at: Any = None,
    payload: dict | None = None,
    attempts_incr: int = 0,
    progress: int | None = None,
    progress_message: str | None = None,
) -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sets = ["status=%s"]
            params: list[Any] = [status]
            if error is not None:
                sets.append("last_error=%s")
                params.append(error[:2000])
            if lease_token is not None:
                sets.append("lease_token=%s")
                params.append(lease_token)
            if lease_expires_at is not None:
                sets.append("lease_expires_at=%s")
                params.append(lease_expires_at)
            if payload is not None:
                sets.append("payload=%s")
                params.append(json.dumps(payload))
            if attempts_incr:
                sets.append("attempts = attempts + %s")
                params.append(attempts_incr)
            if progress is not None:
                sets.append("progress=%s")
                params.append(max(0, min(100, int(progress))))
            if progress_message is not None:
                sets.append("progress_message=%s")
                params.append(progress_message[:200])
            sets.append("updated_at=now()")
            params.append(job_id)
            cur.execute(
                f"UPDATE parse_jobs SET {', '.join(sets)} WHERE id=%s", params
            )
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def switch_primary_source(report_id: str, new_source: str) -> None:
    """主源失效切换（§6.1.2 第5步）：同一事务翻转 is_primary_source + reports.primary_source。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE disclosures SET is_primary_source=false WHERE report_id=%s",
                (report_id,),
            )
            cur.execute(
                "UPDATE disclosures SET is_primary_source=true "
                "WHERE report_id=%s AND source=%s",
                (report_id, new_source),
            )
            cur.execute(
                "UPDATE reports SET primary_source=%s WHERE id=%s",
                (new_source, report_id),
            )
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def mark_pdf_cached(
    report_id: str, source: str, source_announcement_id: str
) -> None:
    """MinIO 对象上传成功后，标记对应披露版本已有持久化 PDF 副本。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE disclosures
                   SET cached_pdf=true
                   WHERE report_id=%s AND source=%s AND source_announcement_id=%s""",
                (report_id, source, source_announcement_id),
            )
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


# ---------------------------------------------------------------------------
# 产物写入（先删旧产物再写，保证幂等，§5.2）
# ---------------------------------------------------------------------------
def write_chunks(report_id: str, version_tag: str, chunks: list[dict]) -> int:
    """将解析分块写入 document_chunks（事务内 DELETE 旧版本 + INSERT）。返回写入条数。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM document_chunks WHERE report_id=%s AND version_tag=%s",
                (report_id, version_tag),
            )
            for c in chunks:
                cur.execute(
                    """INSERT INTO document_chunks
                       (report_id, version_tag, page, seq, text, meta)
                       VALUES (%s, %s, %s, %s, %s, %s::jsonb)""",
                    (
                        report_id,
                        version_tag,
                        c["page"],
                        c["seq"],
                        c["text"],
                        json.dumps(c.get("meta", {})),
                    ),
                )
            conn.commit()
            return len(chunks)
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def read_chunks(report_id: str, version_tag: str) -> list[tuple[int, int, str]]:
    """读回某版本的解析分块（page, seq, text），按 page, seq 排序，供下游阶段还原文本。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT page, seq, text FROM document_chunks "
                "WHERE report_id=%s AND version_tag=%s ORDER BY page, seq",
                (report_id, version_tag),
            )
            return [(row[0], row[1], row[2]) for row in cur.fetchall()]
    finally:
        put_conn(conn)


def write_metrics(report_id: str, version_tag: str, rows: list[dict]) -> int:
    """幂等写入指标卡（§5.2：先 DELETE 本版本旧指标，再 INSERT）。返回写入条数。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM metrics WHERE report_id=%s AND version_tag=%s",
                (report_id, version_tag),
            )
            for r in rows:
                cur.execute(
                    """INSERT INTO metrics
                       (report_id, version_tag, name, source_value, value, derived_value,
                        calculation_formula, is_derived, period_type, value_scope, unit,
                        yoy, qoq, page, caliber, confidence)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        report_id,
                        version_tag,
                        r["name"],
                        r.get("source_value"),
                        r.get("value"),
                        r.get("derived_value"),
                        r.get("calculation_formula"),
                        r.get("is_derived", False),
                        r.get("period_type"),
                        r.get("value_scope"),
                        r.get("unit"),
                        r.get("yoy"),
                        r.get("qoq"),
                        r.get("page"),
                        r.get("caliber"),
                        r.get("confidence"),
                    ),
                )
            conn.commit()
            return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def write_embeddings(
    report_id: str, version_tag: str, vectors: list[dict]
) -> int:
    """将向量写回 document_chunks.embedding（按 page+seq 定位）。幂等（覆盖写）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for v in vectors:
                cur.execute(
                    "UPDATE document_chunks SET embedding=%s::vector "
                    "WHERE report_id=%s AND version_tag=%s AND page=%s AND seq=%s",
                    (
                        json.dumps(v["embedding"]),
                        report_id,
                        version_tag,
                        v["page"],
                        v["seq"],
                    ),
                )
        conn.commit()
        return len(vectors)
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


def search_chunks_vector(
    report_id: str, version_tag: str, query_vec: list[float], top_k: int = 8
) -> list[tuple[int, int, str, float]]:
    """pgvector 余弦相似度检索（1 - cosine_distance）。返回 [(page, seq, text, score)]。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT page, seq, text, 1 - (embedding <=> %s::vector) AS score "
                "FROM document_chunks "
                "WHERE report_id=%s AND version_tag=%s AND embedding IS NOT NULL "
                "ORDER BY embedding <=> %s::vector "
                "LIMIT %s",
                (
                    json.dumps(query_vec),
                    report_id,
                    version_tag,
                    json.dumps(query_vec),
                    top_k,
                ),
            )
            return [(r[0], r[1], r[2], float(r[3])) for r in cur.fetchall()]
    finally:
        put_conn(conn)


def update_disclosure_toc(report_id: str, source: str, toc: list[dict]) -> None:
    """回写本源 PDF 解析出的目录（toc JSONB）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE disclosures SET toc=%s::jsonb "
                "WHERE report_id=%s AND source=%s",
                (json.dumps(toc), report_id, source),
            )
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)


# ---------------------------------------------------------------------------
# 报告级状态流转
# ---------------------------------------------------------------------------
def set_report_status(report_id: str, status: str) -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE reports SET status=%s WHERE id=%s", (status, report_id))
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_conn(conn)
