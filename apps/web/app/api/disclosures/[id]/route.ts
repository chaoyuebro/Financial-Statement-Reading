import { NextRequest } from 'next/server';
import { getDisclosureDetail } from '@/lib/disclosures';

// 报告详情（§7.2 GET /api/disclosures/[id]）
export const dynamic = 'force-dynamic';

export async function GET(_req: NextRequest, { params }: { params: { id: string } }) {
  const detail = await getDisclosureDetail(params.id);
  if (!detail) {
    return Response.json({ error: 'not_found', id: params.id }, { status: 404 });
  }
  return Response.json(detail);
}
