'use client';

import { useState } from 'react';
import { useRouter, usePathname, useSearchParams } from 'next/navigation';
import { Exchange, EXCHANGE_LABELS } from '@fr/shared';
import { SyncLatestButton } from './SyncLatestButton';

const EXCHANGES: Exchange[] = ['sh', 'sz', 'bse'];

export function FilterBar() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const [q, setQ] = useState(params.get('q') ?? '');
  const [exchange, setExchange] = useState(params.get('exchange') ?? '');
  const [dateFrom, setDateFrom] = useState(params.get('dateFrom') ?? '');

  function apply(next: Partial<{ q: string; exchange: string; dateFrom: string }>) {
    const sp = new URLSearchParams(params.toString());
    Object.entries(next).forEach(([k, v]) => {
      if (v) sp.set(k, v);
      else sp.delete(k);
    });
    sp.delete('page');
    router.push(`${pathname}?${sp.toString()}`);
  }

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border border-line bg-surface p-3">
      <label className="flex flex-col gap-1 text-xs text-ink-soft">
        搜索（公司 / 代码）
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && apply({ q: q.trim() || '' })}
          placeholder="如 600519 / 茅台 / maotai"
          aria-label="按公司名称或股票代码搜索"
          className="w-56 rounded border border-line px-3 py-1.5 text-sm text-ink focus-visible:border-accent"
        />
      </label>

      <label className="flex flex-col gap-1 text-xs text-ink-soft">
        交易所
        <select
          value={exchange}
          onChange={(e) => {
            setExchange(e.target.value);
            apply({ exchange: e.target.value });
          }}
          aria-label="按交易所筛选"
          className="rounded border border-line px-3 py-1.5 text-sm text-ink focus-visible:border-accent"
        >
          <option value="">全部</option>
          {EXCHANGES.map((ex) => (
            <option key={ex} value={ex}>
              {EXCHANGE_LABELS[ex]}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-xs text-ink-soft">
        披露日期起
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => {
            setDateFrom(e.target.value);
            apply({ dateFrom: e.target.value });
          }}
          aria-label="按披露日期起始筛选"
          className="rounded border border-line px-3 py-1.5 text-sm text-ink focus-visible:border-accent"
        />
      </label>

      <button
        onClick={() => apply({ q: q.trim() || '' })}
        className="rounded bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90"
      >
        搜索
      </button>

      <SyncLatestButton query={q} />
    </div>
  );
}
