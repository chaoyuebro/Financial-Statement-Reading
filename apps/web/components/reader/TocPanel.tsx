'use client';

import { useEffect, useRef, useState } from 'react';
import { TocItem } from '@fr/shared';

interface Props {
  toc: TocItem[];
  currentPage: number;
  onJump: (page: number) => void;
}

/**
 * 目录面板（§8.2 / W3-3）。
 * - 点击跳页（onJump）
 * - 键盘可达：方向键(↑/↓)漫游焦点、Home/End 跳首尾、Enter/Space 跳页（roving tabindex）
 * - 当前阅读章节高亮，并随滚动自动滚入视野
 */
export function TocPanel({ toc, currentPage, onJump }: Props) {
  // 当前章节：最后一个 page <= currentPage 的条目
  let activeIdx = -1;
  for (let i = 0; i < toc.length; i++) {
    if (toc[i].page <= currentPage) activeIdx = i;
    else break;
  }

  const [focusIdx, setFocusIdx] = useState(0);
  const btnRefs = useRef<(HTMLButtonElement | null)[]>([]);

  // 阅读位置变化（翻页/滚动）时，若当前章节条目移出可视区则自动滚入
  useEffect(() => {
    if (activeIdx < 0) return;
    btnRefs.current[activeIdx]?.scrollIntoView({ block: 'nearest' });
  }, [activeIdx]);

  const focusItem = (idx: number) => {
    const last = toc.length - 1;
    const clamped = Math.max(0, Math.min(last, idx));
    setFocusIdx(clamped);
    btnRefs.current[clamped]?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        focusItem(focusIdx + 1);
        break;
      case 'ArrowUp':
        e.preventDefault();
        focusItem(focusIdx - 1);
        break;
      case 'Home':
        e.preventDefault();
        focusItem(0);
        break;
      case 'End':
        e.preventDefault();
        focusItem(toc.length - 1);
        break;
      case 'Enter':
      case ' ':
        // 按钮原生会触发 onClick 跳页；此处显式确保跳转到当前焦点条目
        e.preventDefault();
        if (toc[focusIdx]) onJump(toc[focusIdx].page);
        break;
      default:
        break;
    }
  };

  if (!toc.length) {
    return (
      <nav
        aria-label="报告目录"
        className="flex w-64 shrink-0 flex-col overflow-hidden border-r border-line bg-surface"
      >
        <h2 className="border-b border-line px-4 py-3 text-sm font-semibold">目录</h2>
        <p className="p-4 text-sm text-ink-soft">本份报告暂无目录（解析后生成）。</p>
      </nav>
    );
  }

  return (
    <nav
      aria-label="报告目录"
      className="flex w-64 shrink-0 flex-col overflow-hidden border-r border-line bg-surface"
      onKeyDown={onKeyDown}
    >
      <div className="border-b border-line px-4 py-3">
        <h2 className="text-sm font-semibold">目录</h2>
        <p className="mt-0.5 text-[10px] text-ink-soft">P. 表示 PDF 页码</p>
      </div>
      <ul role="list" className="min-h-0 flex-1 overflow-auto py-1">
        {toc.map((t, i) => {
          const active = i === activeIdx;
          const isFocusTarget = i === focusIdx;
          return (
            <li key={`${t.page}-${i}`}>
              <button
                type="button"
                ref={(el) => {
                  btnRefs.current[i] = el;
                }}
                tabIndex={isFocusTarget ? 0 : -1}
                onClick={() => {
                  setFocusIdx(i);
                  onJump(t.page);
                }}
                aria-current={active ? 'true' : undefined}
                aria-label={`第 ${t.page} 页：${t.title}`}
                className={[
                  'flex w-full items-baseline gap-2 px-4 py-2 text-left text-sm transition-colors',
                  t.level === 2 ? 'pl-8' : '',
                  active ? 'bg-accent-soft font-medium text-accent' : 'text-ink hover:bg-accent-soft/50',
                  isFocusTarget ? 'outline-none ring-2 ring-inset ring-accent' : '',
                ].join(' ')}
              >
                <span className="min-w-0 flex-1 truncate">{t.title}</span>
                <span
                  className="ml-auto shrink-0 rounded bg-surface-muted px-1.5 py-0.5 text-[10px] tabular-nums text-ink-soft"
                  title={`PDF 第 ${t.page} 页`}
                >
                  P.{t.page}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
