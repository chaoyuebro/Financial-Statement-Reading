import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';
export const maxDuration = 240;

export async function POST() {
  const workerUrl = process.env.WORKER_ENQUEUE_URL;
  const token = process.env.WORKER_API_TOKEN;
  if (!workerUrl || !token) {
    return NextResponse.json({ error: '同步服务尚未配置' }, { status: 503 });
  }

  const syncUrl = new URL('/internal/sync', workerUrl).toString();
  try {
    const response = await fetch(syncUrl, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ days: 45, max_pages: 40 }),
      cache: 'no-store',
      signal: AbortSignal.timeout(220_000),
    });
    const data = await response.json().catch(() => ({ error: '同步服务返回格式错误' }));
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    const message = error instanceof Error ? error.message : '同步服务不可用';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
