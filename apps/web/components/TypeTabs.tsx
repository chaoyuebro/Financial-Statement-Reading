'use client';

import { useRouter, usePathname, useSearchParams } from 'next/navigation';
import { DisclosureType, TYPE_LABELS } from '@fr/shared';

const TABS: DisclosureType[] = ['annual', 'halfyear', 'quarterly', 'prospectus'];

export function TypeTabs() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const active = params.get('type');

  function select(t: DisclosureType | null) {
    const sp = new URLSearchParams(params.toString());
    if (t) sp.set('type', t);
    else sp.delete('type');
    sp.delete('page'); // 切换类型回到第一页
    router.push(`${pathname}?${sp.toString()}`);
  }

  const tabClass = (on: boolean) =>
    `rounded-full px-4 py-1.5 text-sm font-medium transition-colors ` +
    (on ? 'bg-accent text-white' : 'border border-line bg-surface text-ink-soft hover:bg-surface-muted');

  return (
    <div role="tablist" aria-label="报告类型筛选" className="flex flex-wrap gap-2">
      <button role="tab" aria-selected={!active} onClick={() => select(null)} className={tabClass(!active)}>
        全部
      </button>
      {TABS.map((t) => (
        <button
          key={t}
          role="tab"
          aria-selected={active === t}
          onClick={() => select(t)}
          className={tabClass(active === t)}
        >
          {TYPE_LABELS[t]}
        </button>
      ))}
    </div>
  );
}
