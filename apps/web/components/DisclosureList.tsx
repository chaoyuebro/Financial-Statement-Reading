'use client';

import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useRouter, useSearchParams } from 'next/navigation';
import { DisclosureListItem, ListResponse } from '@fr/shared';
import { DisclosureCard } from './DisclosureCard';

interface Props {
  items: DisclosureListItem[];
  hasMore: boolean;
}

function DisclosureListInner({ items, hasMore }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const parentRef = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);
  const [rows, setRows] = useState(items);
  const [page, setPage] = useState(1);
  const [more, setMore] = useState(hasMore);
  const [loading, setLoading] = useState(false);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 78,
    overscan: 6,
  });

  useEffect(() => {
    setRows(items);
    setPage(1);
    setMore(hasMore);
    setActive(0);
  }, [items, hasMore]);

  const loadMore = useCallback(async () => {
    if (!more || loading) return;
    setLoading(true);
    try {
      const nextPage = page + 1;
      const sp = new URLSearchParams(searchParams.toString());
      sp.set('page', String(nextPage));
      sp.set('pageSize', '50');
      const response = await fetch(`/api/disclosures?${sp.toString()}`);
      if (!response.ok) return;
      const data = (await response.json()) as ListResponse;
      setRows((current) => {
        const ids = new Set(current.map((item) => item.id));
        return [...current, ...data.items.filter((item) => !ids.has(item.id))];
      });
      setPage(nextPage);
      setMore(data.hasMore);
    } finally {
      setLoading(false);
    }
  }, [loading, more, page, searchParams]);

  // 键盘导航：上下移动 active，并滚动到可见 + 聚焦
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (rows.length === 0) return;
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          setActive((a) => Math.min(rows.length - 1, a + 1));
          break;
        case 'ArrowUp':
          e.preventDefault();
          setActive((a) => Math.max(0, a - 1));
          break;
        case 'Home':
          e.preventDefault();
          setActive(0);
          break;
        case 'End':
          e.preventDefault();
          setActive(items.length - 1);
          break;
      }
    },
    [rows.length],
  );

  useEffect(() => {
    if (rows.length === 0) return;
    virtualizer.scrollToIndex(active, { align: 'auto' });
  }, [active, virtualizer, rows.length]);

  // active 变化后聚焦对应卡片按钮（虚拟滚动下需等渲染）
  useEffect(() => {
    if (rows.length === 0) return;
    const id = requestAnimationFrame(() => {
      const el = parentRef.current?.querySelector<HTMLElement>(
        `[data-index="${active}"] [data-card-button]`,
      );
      el?.focus();
    });
    return () => cancelAnimationFrame(id);
  }, [active, rows.length]);

  const activateItem = useCallback(
    (index: number) => {
      const item = rows[index];
      if (!item) return;
      setActive(index);
      const query = searchParams.toString();
      const returnTo = query ? `/?${query}` : '/';
      router.push(
        `/reader/${encodeURIComponent(item.id)}?returnTo=${encodeURIComponent(returnTo)}`,
      );
    },
    [rows, router, searchParams],
  );

  if (rows.length === 0) {
    return (
      <p role="status" className="rounded-lg border border-line bg-surface p-8 text-center text-ink-soft">
        暂无匹配的披露。试试调整筛选或搜索词。
      </p>
    );
  }

  return (
    <div
      ref={parentRef}
      role="list"
      aria-label="披露列表"
      aria-activedescendant={`disclosure-${active}`}
      tabIndex={0}
      onKeyDown={onKeyDown}
      onScroll={(event) => {
        const el = event.currentTarget;
        if (el.scrollHeight - el.scrollTop - el.clientHeight < 320) {
          void loadMore();
        }
      }}
      className="h-[68vh] overflow-auto rounded-lg border border-line bg-surface p-2"
    >
      <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
        {virtualizer.getVirtualItems().map((vi) => {
          const item = rows[vi.index];
          const isActive = vi.index === active;
          return (
            <div
              key={item.id}
              data-index={vi.index}
              role="listitem"
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${vi.start}px)`,
                height: vi.size,
                padding: '4px 0',
              }}
            >
              <DisclosureCard
                item={item}
                active={isActive}
                tabIndex={isActive ? 0 : -1}
                onActivate={() => activateItem(vi.index)}
                onFocus={() => setActive(vi.index)}
              />
            </div>
          );
        })}
      </div>
      {loading && (
        <p className="sticky bottom-0 bg-surface/90 py-2 text-center text-xs text-ink-soft">
          正在加载更多披露…
        </p>
      )}
    </div>
  );
}

export const DisclosureList = memo(DisclosureListInner);
