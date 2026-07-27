import { Suspense } from 'react';
import { listDisclosures } from '@/lib/disclosures';
import { DisclosureType, Exchange } from '@fr/shared';
import { TypeTabs } from '@/components/TypeTabs';
import { FilterBar } from '@/components/FilterBar';
import { DisclosureList } from '@/components/DisclosureList';

// 直连 Postgres，按 searchParams 动态渲染（SSR）
export const dynamic = 'force-dynamic';

type SearchParams = Record<string, string | string[] | undefined>;

export default async function HomePage({ searchParams }: { searchParams: SearchParams }) {
  const get = (k: string): string | undefined =>
    typeof searchParams[k] === 'string' ? (searchParams[k] as string) : undefined;

  const result = await listDisclosures({
    type: get('type') as DisclosureType | undefined,
    exchange: get('exchange') as Exchange | undefined,
    q: get('q'),
    dateFrom: get('dateFrom'),
    dateTo: get('dateTo'),
    page: get('page') ? Number(get('page')) : 1,
    pageSize: 50,
  });

  return (
    <main className="min-h-screen bg-surface-muted text-ink">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto max-w-5xl px-4 py-4">
          <h1 className="text-lg font-semibold">财报阅读 · 辅助阅读工具</h1>
          <p className="mt-1 text-sm text-ink-soft">披露列表（W2 · BFF + SSR）</p>
        </div>
      </header>

      <section className="mx-auto max-w-5xl space-y-4 px-4 py-6">
        <Suspense fallback={<div className="h-9" />}>
          <TypeTabs />
        </Suspense>
        <Suspense fallback={<div className="h-20" />}>
          <FilterBar />
        </Suspense>

        <DisclosureList items={result.items} hasMore={result.hasMore} />

        <p className="text-sm text-ink-soft" role="status">
          共 {result.total} 条{result.hasMore ? '，还有更多' : '，已显示全部'}
          {result.items.length === 0 ? '。' : `（当前显示 ${result.items.length} 条）。`}
        </p>
      </section>
    </main>
  );
}
