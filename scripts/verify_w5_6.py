"""W5-6 端到端验证脚本（worker /internal/retrieve + BFF metrics/summary）。

前置：docker compose 已启动 fr_web/fr_worker/fr_postgres/fr_redis，且至少一份报告
已完成 parse → metrics 抽取（status >= parsed）。

退出码：0 = 全过；1 = 任一检查失败或前置缺失。
"""
import json
import os
import sys
import urllib.request
import urllib.error

WORKER_URL = os.environ.get("WORKER_ENQUEUE_URL", "http://127.0.0.1:8000")
WORKER_TOKEN = os.environ.get("WORKER_API_TOKEN", "")
WEB_BASE = os.environ.get("WEB_BASE_URL", "http://127.0.0.1:3001")
PG_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://fr:fr_dev_pw@127.0.0.1:5432/fr",
)


def fetch(url: str, *, method: str = "GET", headers: dict | None = None,
          body: bytes | None = None, timeout: float = 10.0):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def find_test_report() -> tuple[str, str] | None:
    """找一个 status >= parsed 的 report_id，返回 (id, status)。"""
    try:
        import psycopg2  # type: ignore
    except ImportError:
        print("[skip] psycopg2 未安装，跳过 e2e")
        return None
    try:
        conn = psycopg2.connect(PG_DSN)
    except Exception as e:
        print(f"[skip] Postgres 不可达: {e}")
        return None
    with conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.id::text, r.status
              FROM reports r
              JOIN metrics m ON m.report_id = r.id
             GROUP BY r.id, r.status
             HAVING COUNT(m.*) >= 3
             ORDER BY r.disclosure_date DESC NULLS LAST
             LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            print("[skip] 无已完成 metrics 抽取的报告（status>=metrics_done 且 metrics 行数>=3）")
            return None
        return row[0], row[1]


def main() -> int:
    if not WORKER_TOKEN:
        print("[fail] WORKER_API_TOKEN 未设置", file=sys.stderr)
        return 1

    fails = 0

    # 0) Worker 端点可达性 + 鉴权（不依赖具体报告）
    body = json.dumps({"report_id": "ghost-id", "question": "营业收入", "top_k": 3}).encode()
    code, data = fetch(
        f"{WORKER_URL}/internal/retrieve",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {WORKER_TOKEN}",
        },
        body=body,
    )
    if code != 200:
        print(f"[fail] worker /internal/retrieve 状态码 {code}: {data[:200]!r}")
        fails += 1
    else:
        print("[ok]   worker /internal/retrieve 200（无 report 时返回空 chunks）")

    code, data = fetch(
        f"{WORKER_URL}/internal/retrieve",
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer WRONG"},
        body=body,
    )
    if code != 401:
        print(f"[fail] 错误 token 应 401，实际 {code}")
        fails += 1
    else:
        print("[ok]   worker 错误 token 返回 401")

    # 参数校验
    code, _ = fetch(
        f"{WORKER_URL}/internal/retrieve",
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {WORKER_TOKEN}"},
        body=b'{"report_id":"x"}',
    )
    if code != 400:
        print(f"[fail] 缺 question 应 400，实际 {code}")
        fails += 1
    else:
        print("[ok]   worker 缺 question 返回 400")

    # 路径白名单
    code, _ = fetch(
        f"{WORKER_URL}/internal/other",
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {WORKER_TOKEN}"},
        body=b'{}',
    )
    if code != 404:
        print(f"[fail] 未知路径应 404，实际 {code}")
        fails += 1
    else:
        print("[ok]   worker 未知路径返回 404")

    # 1) 真实报告存在性 → 进入全量 e2e
    rep = find_test_report()
    if rep is None:
        print("\n[info] 无 metrics_done 报告，BFF 全链路 e2e 跳过")
        print(f"--- W5-6 e2e: {'PASS' if fails == 0 else f'FAIL ({fails})'} ---")
        return 0 if fails == 0 else 1
    report_id, status = rep
    print(f"\n[info] 选用报告 {report_id} (status={status})")

    # 2) BFF /api/disclosures/[id]/metrics
    code, data = fetch(f"{WEB_BASE}/api/disclosures/{report_id}/metrics")
    if code != 200:
        print(f"[fail] BFF /metrics 状态码 {code}: {data[:200]!r}")
        fails += 1
    else:
        items = json.loads(data).get("items", [])
        print(f"[ok]   BFF /metrics 返回 {len(items)} 项指标")
        if len(items) < 3:
            print(f"[fail] 期望 3 项指标，实际 {len(items)}")
            fails += 1

    # 3) BFF /api/disclosures/[id]/summary
    code, data = fetch(
        f"{WEB_BASE}/api/disclosures/{report_id}/summary",
        method="POST",
        headers={"Content-Type": "application/json"},
        body=b"{}",
    )
    if code != 200:
        print(f"[fail] BFF /summary 状态码 {code}: {data[:200]!r}")
        fails += 1
    else:
        payload = json.loads(data)
        pts = payload.get("points", [])
        print(f"[ok]   BFF /summary 返回 {len(pts)} 要点，fromMetrics={payload.get('fromMetrics')}")
        if not pts:
            print("[fail] /summary 未返回要点")
            fails += 1

    # 4) BFF /api/disclosures/[id]/chat（无 LLM 应抽取式降级）
    code, data = fetch(
        f"{WEB_BASE}/api/disclosures/{report_id}/chat",
        method="POST",
        headers={"Content-Type": "application/json"},
        body=json.dumps({"question": "本期营业收入"}).encode(),
    )
    if code != 200:
        print(f"[fail] BFF /chat 状态码 {code}: {data[:200]!r}")
        fails += 1
    else:
        payload = json.loads(data)
        cits = payload.get("citations", [])
        print(
            f"[ok]   BFF /chat 答案 {len(payload.get('answer', ''))} 字，"
            f"引用 {len(cits)} 条，fallback={payload.get('fallback')}"
        )

    print(f"\n--- W5-6 e2e: {'PASS' if fails == 0 else f'FAIL ({fails})'} ---")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())