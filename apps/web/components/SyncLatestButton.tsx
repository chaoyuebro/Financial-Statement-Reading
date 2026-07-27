'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

type SyncResult = {
  synced?: number;
  date_from?: string;
  date_to?: string;
  error?: string;
  company?: string;
};

export function SyncLatestButton({ query = '' }: { query?: string }) {
  const router = useRouter();
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState('');
  const [failed, setFailed] = useState(false);

  const syncLatest = async () => {
    if (syncing) return;
    setSyncing(true);
    setFailed(false);
    setMessage('正在从巨潮资讯同步，请稍候…');
    try {
      const response = await fetch('/api/sync/latest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ q: query.trim() }),
      });
      const result = (await response.json()) as SyncResult;
      if (!response.ok) throw new Error(result.error || '同步失败');

      setMessage(
        `同步完成：${result.company ? `${result.company}定向` : '全市场'}处理 ${result.synced ?? 0} 条披露（${result.date_from} 至 ${result.date_to}）`,
      );
      router.refresh();
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : '同步失败，请稍后重试');
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        onClick={syncLatest}
        disabled={syncing}
        className="inline-flex h-9 items-center gap-2 rounded-md bg-accent px-4 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-wait disabled:opacity-60"
      >
        <span aria-hidden="true" className={syncing ? 'animate-spin' : ''}>
          ↻
        </span>
        {syncing ? '正在同步' : '同步最新'}
      </button>
      {message && (
        <p
          role="status"
          className={`text-sm ${failed ? 'text-red-600' : 'text-ink-soft'}`}
        >
          {message}
        </p>
      )}
    </div>
  );
}
