// POST /api/disclosures/[id]/summary — 一键摘要（§7.3 §MVP 由指标派生）
// MVP 策略：直接从 metrics 表派生 3~5 条要点，引用指向指标所在页。无 LLM 依赖，可离线运行。

import { NextRequest } from 'next/server';
import { dbQuery } from '@/lib/db';
import { formatCny, formatPercent } from '@/lib/format';
import { METRIC_LABELS, type MetricRow, type SummaryResponse, type SummaryPoint } from '@fr/shared';

export const dynamic = 'force-dynamic';

interface MetricsRow {
  name: MetricRow['name'];
  value: number | string;
  unit: string;
  yoy: number | null;
  qoq: number | null;
  page: number | null;
  confidence: number;
}

interface ReportMetaRow {
  company_name: string;
  company_code: string;
  type: string;
  report_period: string;
}

function fmtMetricText(name: MetricRow['name'], m: MetricsRow): string {
  const v = typeof m.value === 'string' ? Number(m.value) : m.value;
  const amount = formatCny(v);
  const yoy = formatPercent(m.yoy == null ? null : Number(m.yoy));
  return `${METRIC_LABELS[name]}：${amount}（同比 ${yoy}）`;
}

export async function POST(_req: NextRequest, { params }: { params: { id: string } }) {
  const meta = await dbQuery<ReportMetaRow>(
    `SELECT c.name AS company_name, c.code AS company_code, r.type, r.report_period
     FROM reports r JOIN companies c ON c.code = r.company_code WHERE r.id = $1`,
    [params.id],
  );
  if (meta.length === 0) {
    return Response.json({ error: 'not_found', id: params.id }, { status: 404 });
  }
  const rows = await dbQuery<MetricsRow>(
    `SELECT name, value, unit, yoy, qoq, page, confidence
     FROM metrics WHERE report_id = $1 ORDER BY name ASC`,
    [params.id],
  );
  if (rows.length === 0) {
    return Response.json(
      { error: 'not_ready', message: '指标尚未抽取完成' },
      { status: 404 },
    );
  }
  const m = meta[0];
  const header = `${m.company_name}（${m.company_code}）${m.report_period} 报告关键指标`;
  const points: SummaryPoint[] = rows.map((row) => {
    const page = row.page ?? 1;
    const text = fmtMetricText(row.name, row);
    const label = METRIC_LABELS[row.name] ?? row.name;
    return {
      text,
      citations: [{ page, text: `${label} ${formatCny(typeof row.value === 'string' ? Number(row.value) : row.value)}` }],
    };
  });

  const body: SummaryResponse = {
    reportId: params.id,
    points: [{ text: header, citations: [] }, ...points],
    generatedAt: new Date().toISOString(),
    model: null,
    fromMetrics: true,
  };
  return Response.json(body);
}