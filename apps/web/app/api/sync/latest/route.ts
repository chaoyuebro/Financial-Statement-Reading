import { NextResponse } from 'next/server';
import { pgPool } from '@/lib/db';

export const dynamic = 'force-dynamic';
export const maxDuration = 240;

export async function POST(request: Request) {
  const workerUrl = process.env.WORKER_ENQUEUE_URL;
  const token = process.env.WORKER_API_TOKEN;
  if (!workerUrl || !token) {
    return NextResponse.json({ error: '同步服务尚未配置' }, { status: 503 });
  }

  const body = await request.json().catch(() => ({}));
  const query = typeof body.q === 'string' ? body.q.trim() : '';
  let stock = '';
  let company = '';
  if (query) {
    const result = await pgPool.query<{
      code: string;
      short_name: string;
      org_id: string | null;
    }>(
      `SELECT code, short_name, org_id
       FROM companies
       WHERE code = $1 OR name ILIKE ($1 || '%') OR short_name ILIKE ($1 || '%')
       ORDER BY CASE WHEN code = $1 THEN 0 WHEN short_name = $1 THEN 1 ELSE 2 END
       LIMIT 1`,
      [query],
    );
    const matched = result.rows[0];
    if (matched?.org_id) {
      stock = `${matched.code},${matched.org_id}`;
      company = `${matched.short_name}（${matched.code}）`;
    }
  }

  const syncUrl = new URL('/internal/sync', workerUrl).toString();
  try {
    const response = await fetch(syncUrl, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ days: 45, max_pages: stock ? 100 : 40, stock }),
      cache: 'no-store',
      signal: AbortSignal.timeout(220_000),
    });
    const data = await response.json().catch(() => ({ error: '同步服务返回格式错误' }));
    return NextResponse.json({ ...data, company: company || undefined }, { status: response.status });
  } catch (error) {
    const message = error instanceof Error ? error.message : '同步服务不可用';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
