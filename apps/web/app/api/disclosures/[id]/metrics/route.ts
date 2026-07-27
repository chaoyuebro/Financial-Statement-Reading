// GET /api/disclosures/[id]/metrics — 读取 metrics 表，三项核心指标（§6.5 / §7.3）
// 期望数据：metrics 行按 name 排序返回；缺失则 404 not_ready（前端提示稍后重试）。

import { NextRequest } from 'next/server';
import { dbQuery } from '@/lib/db';
import { METRIC_LABELS, type MetricRow } from '@fr/shared';

export const dynamic = 'force-dynamic';

interface MetricsRow {
  name: MetricRow['name'];
  value: number | string; // pg bigint -> string
  unit: string;
  caliber: string;
  value_scope: string;
  yoy: number | null;
  qoq: number | null;
  page: number | null;
  confidence: number;
}

export async function GET(_req: NextRequest, { params }: { params: { id: string } }) {
  // 先校验报告存在
  const r = await dbQuery<{ status: string }>(`SELECT status FROM reports WHERE id = $1`, [params.id]);
  if (r.length === 0) {
    return Response.json({ error: 'not_found', id: params.id }, { status: 404 });
  }
  const rows = await dbQuery<MetricsRow>(
    `SELECT name, value, unit, caliber, value_scope, yoy, qoq, page, confidence
     FROM metrics WHERE report_id = $1 ORDER BY name ASC`,
    [params.id],
  );
  if (rows.length === 0) {
    return Response.json(
      { error: 'not_ready', status: r[0].status, message: '指标尚未抽取完成' },
      { status: 404 },
    );
  }
  const items: MetricRow[] = rows.map((m) => ({
    name: m.name,
    label: METRIC_LABELS[m.name] ?? m.name,
    value: typeof m.value === 'string' ? Number(m.value) : m.value,
    unit: m.unit,
    caliber: m.caliber,
    valueScope: m.value_scope,
    yoy: m.yoy == null ? null : Number(m.yoy),
    qoq: m.qoq == null ? null : Number(m.qoq),
    page: m.page,
    confidence: Number(m.confidence),
  }));
  return Response.json({ reportId: params.id, items });
}