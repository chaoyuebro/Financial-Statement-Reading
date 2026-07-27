import { NextRequest, NextResponse } from 'next/server';
import { listDisclosures, ListQueryParams } from '@/lib/disclosures';
import { DisclosureType, Exchange } from '@fr/shared';

// 直连 Postgres，不缓存
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;

  const params: ListQueryParams = {
    type: (sp.get('type') as DisclosureType) || undefined,
    exchange: (sp.get('exchange') as Exchange) || undefined,
    q: sp.get('q') || undefined,
    dateFrom: sp.get('dateFrom') || undefined,
    dateTo: sp.get('dateTo') || undefined,
    page: sp.get('page') ? Number(sp.get('page')) : undefined,
    pageSize: sp.get('pageSize') ? Number(sp.get('pageSize')) : undefined,
  };

  try {
    const result = await listDisclosures(params);
    return NextResponse.json(result);
  } catch (e) {
    console.error('[GET /api/disclosures] error', e);
    return NextResponse.json({ error: 'internal_error' }, { status: 500 });
  }
}
