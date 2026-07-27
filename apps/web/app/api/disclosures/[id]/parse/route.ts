import { NextRequest, NextResponse } from 'next/server';
import { pgPool } from '@/lib/db';

// 解析触发路由（§5.1 / §6.1.3）
// POST：触发该报告的解析管线（经内部 Worker 入队端点，仅 127.0.0.1 可达 + Bearer 鉴权）
// GET ：返回当前报告状态与是否可触发（供前端按钮态展示）
export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

// 内部 Worker 入队端点（与 worker/config.py 的 ENQUEUE_HOST/PORT/WORKER_API_TOKEN 对齐）
const ENQUEUE_URL =
  process.env.WORKER_ENQUEUE_URL || 'http://127.0.0.1:8700/internal/enqueue';
const WORKER_TOKEN = process.env.WORKER_API_TOKEN || 'dev-worker-token-change-me';

/** 报告守卫：存在 + 非临时报告(report_period_unknown) + 非已撤回，才允许触发解析。 */
async function guardReport(id: string): Promise<{
  ok: boolean;
  status?: string;
  reportPeriodUnknown?: boolean;
  isWithdrawn?: boolean;
}> {
  const res = await pgPool.query<{
    status: string;
    report_period_unknown: boolean;
    is_withdrawn: boolean;
  }>(
    `SELECT status, report_period_unknown, is_withdrawn
     FROM reports WHERE id = $1`,
    [id],
  );
  if (res.rowCount === 0) {
    return { ok: false };
  }
  const r = res.rows[0];
  if (r.report_period_unknown || r.is_withdrawn) {
    return {
      ok: false,
      status: r.status,
      reportPeriodUnknown: r.report_period_unknown,
      isWithdrawn: r.is_withdrawn,
    };
  }
  return { ok: true, status: r.status };
}

export async function GET(
  _req: NextRequest,
  { params }: { params: { id: string } },
) {
  const g = await guardReport(params.id);
  if (!g.ok && g.status === undefined) {
    return NextResponse.json({ error: 'not found' }, { status: 404 });
  }
  return NextResponse.json({
    id: params.id,
    status: g.status,
    canParse: g.ok,
    reportPeriodUnknown: g.reportPeriodUnknown ?? false,
    isWithdrawn: g.isWithdrawn ?? false,
  });
}

export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  // 1) 服务端守卫（防御纵深：避免无谓的内部网络调用，也防止越权触发临时报告）
  const g = await guardReport(params.id);
  if (!g.ok) {
    if (g.status === undefined) {
      return NextResponse.json({ error: 'not found' }, { status: 404 });
    }
    return NextResponse.json(
      {
        error: 'report not parseable',
        reason: g.reportPeriodUnknown
          ? 'report_period_unknown'
          : 'withdrawn',
        status: g.status,
      },
      { status: 409 },
    );
  }

  // 2) 调用内部 Worker 入队端点（Bearer 鉴权）
  let body: { stage?: string; source?: string; payload?: unknown } = {};
  try {
    body = await req.json();
  } catch {
    // 空 body 视为从 download 阶段启动
  }
  const stage = body.stage || 'download';

  let upstream: Response;
  try {
    upstream = await fetch(ENQUEUE_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${WORKER_TOKEN}`,
      },
      body: JSON.stringify({
        report_id: params.id,
        stage,
        source: body.source,
        payload: body.payload,
      }),
      // 内部调用不做长超时等待；不可达即 502
      signal: AbortSignal.timeout(10_000),
    });
  } catch {
    // Worker 入队端点不可达（未启动 / 网络隔离）
    return NextResponse.json(
      { error: 'worker enqueue unreachable' },
      { status: 502 },
    );
  }

  const data = await upstream.json().catch(() => ({}));
  if (upstream.status === 200) {
    return NextResponse.json({
      triggered: true,
      jobId: data.job_id,
      created: data.created,
      stage,
    });
  }
  // 401/409 等透传
  return NextResponse.json(
    { error: data.error || 'enqueue failed', status: upstream.status },
    { status: upstream.status || 502 },
  );
}
