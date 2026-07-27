'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  DisclosureDetail,
  TYPE_LABELS,
  STATUS_LABELS,
  type MetricRow,
  type SummaryResponse,
  type ChatResponse,
  type Citation,
} from '@fr/shared';
import { formatCny, formatPercent, formatValueScope } from '@/lib/format';

// AI 面板（W5–6e）：指标卡 / 一键摘要 / 问答，全部接 BFF，引用跳页+高亮由 ReaderPage 注入。

export interface CitationJump {
  (page: number, text: string): void;
}

export function AiPanel({
  detail,
  onCite,
}: {
  detail: DisclosureDetail;
  onCite: CitationJump;
}) {
  const [status, setStatus] = useState(detail.status);
  const [parseError, setParseError] = useState<string | null>(null);

  useEffect(() => {
    if (status !== 'pending') return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const r = await fetch(`/api/disclosures/${detail.id}/parse`);
        const data = (await r.json()) as { status?: typeof detail.status };
        if (cancelled || !r.ok || !data.status) return;
        setStatus(data.status);
        if (data.status === 'metrics_done') {
          window.location.reload();
          return;
        }
        if (data.status === 'failed') {
          setParseError('报告解析失败，请重试');
          return;
        }
        timer = setTimeout(poll, 1500);
      } catch {
        if (!cancelled) timer = setTimeout(poll, 2500);
      }
    };

    fetch(`/api/disclosures/${detail.id}/parse`, { method: 'POST' })
      .then(async (r) => {
        if (!r.ok && r.status !== 409) {
          const data = (await r.json().catch(() => ({}))) as { error?: string };
          throw new Error(data.error ?? '无法启动解析');
        }
        if (!cancelled) timer = setTimeout(poll, 800);
      })
      .catch((e: unknown) => {
        if (!cancelled) setParseError(e instanceof Error ? e.message : '无法启动解析');
      });

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [detail.id, status]);

  const processing = !['metrics_done', 'ready'].includes(status);

  return (
    <div className="flex h-full flex-col">
      <Header detail={{ ...detail, status }} />
      <div className="flex-1 space-y-4 overflow-auto p-4">
        {processing ? (
          <Section title="报告解析">
            <p className={parseError ? 'text-xs text-rose-600' : 'text-xs text-ink-soft'}>
              {parseError ?? '正在提取全文、指标并建立问答索引…'}
            </p>
          </Section>
        ) : (
          <>
            <MetricsSection reportId={detail.id} onCite={onCite} />
            <SummarySection reportId={detail.id} onCite={onCite} />
            <ChatSection reportId={detail.id} onCite={onCite} />
          </>
        )}
      </div>
    </div>
  );
}

function Header({ detail }: { detail: DisclosureDetail }) {
  return (
    <div className="border-b border-line px-4 py-3">
      <h2 className="text-sm font-semibold">AI 辅助</h2>
      <p className="mt-1 text-xs text-ink-soft">
        {TYPE_LABELS[detail.type]} · {detail.reportPeriod} · 状态 {STATUS_LABELS[detail.status]}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 指标卡
// ---------------------------------------------------------------------------

function MetricsSection({ reportId, onCite }: { reportId: string; onCite: CitationJump }) {
  const [items, setItems] = useState<MetricRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/disclosures/${reportId}/metrics`)
      .then(async (r) => {
        const data = (await r.json()) as { items?: MetricRow[]; message?: string; error?: string };
        if (cancelled) return;
        if (r.ok && data.items) setItems(data.items);
        else setErr(data.message ?? data.error ?? '尚未就绪');
      })
      .catch((e: unknown) => !cancelled && setErr(e instanceof Error ? e.message : '网络错误'));
    return () => {
      cancelled = true;
    };
  }, [reportId]);

  if (err) {
    return (
      <Section title="关键指标">
        <p className="text-xs text-ink-soft">{err}</p>
      </Section>
    );
  }
  if (!items) {
    return (
      <Section title="关键指标">
        <p className="text-xs text-ink-soft" aria-live="polite">加载中…</p>
      </Section>
    );
  }
  return (
    <Section title="关键指标">
      <ul className="space-y-2">
        {items.map((m) => (
          <li key={m.name}>
            <MetricCard metric={m} onCite={onCite} />
          </li>
        ))}
      </ul>
    </Section>
  );
}

function MetricCard({ metric, onCite }: { metric: MetricRow; onCite: CitationJump }) {
  const yoyUp = (metric.yoy ?? 0) >= 0;
  return (
    <button
      type="button"
      onClick={() => metric.page != null && onCite(metric.page, metric.label)}
      className="block w-full rounded-lg border border-line p-3 text-left transition hover:border-accent hover:bg-accent-soft/40 focus:outline-none focus:ring-2 focus:ring-accent"
      aria-label={`跳转到第 ${metric.page ?? '?'} 页查看「${metric.label}」`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs text-ink-soft">{metric.label}</span>
        {metric.page != null && (
          <span className="text-[10px] text-accent" aria-hidden>p.{metric.page}</span>
        )}
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-base font-semibold tabular-nums">{formatCny(metric.value)}</span>
        {metric.yoy != null && (
          <span
            className={`text-xs tabular-nums ${yoyUp ? 'text-rose-600' : 'text-emerald-600'}`}
            aria-label={yoyUp ? '同比上升' : '同比下降'}
          >
            {yoyUp ? '↑' : '↓'} {formatPercent(metric.yoy)}
          </span>
        )}
      </div>
      <div className="mt-1 text-[10px] text-ink-soft">
        口径 {metric.caliber} · {formatValueScope(metric.valueScope)} ·
        置信度 {(metric.confidence * 100).toFixed(0)}%
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// 一键摘要
// ---------------------------------------------------------------------------

function SummarySection({ reportId, onCite }: { reportId: string; onCite: CitationJump }) {
  const [data, setData] = useState<SummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const r = await fetch(`/api/disclosures/${reportId}/summary`, { method: 'POST' });
      const d = (await r.json()) as SummaryResponse & { message?: string };
      if (!r.ok) {
        setErr(d.message ?? '生成失败');
      } else {
        setData(d);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : '网络错误');
    } finally {
      setLoading(false);
    }
  }, [reportId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Section title="一键摘要">
      {loading && <p className="text-xs text-ink-soft">生成中…</p>}
      {err && (
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-rose-600">{err}</p>
          <button type="button" onClick={() => void load()} className="text-xs text-accent hover:underline">
            重试
          </button>
        </div>
      )}
      {data && (
        <ul className="space-y-2 text-sm">
          {data.points.map((p, i) => (
            <li key={i} className="rounded border border-line p-2">
              <p className="leading-relaxed">{p.text}</p>
              {p.citations.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {p.citations.map((c, j) => (
                    <CitationChip key={j} citation={c} onCite={onCite} />
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// 问答
// ---------------------------------------------------------------------------

interface Msg {
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  fallback?: boolean;
  model?: string | null;
}

function ChatSection({ reportId, onCite }: { reportId: string; onCite: CitationJump }) {
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const ask = useCallback(async () => {
    const text = q.trim();
    if (!text || busy) return;
    setQ('');
    setErr(null);
    const next: Msg[] = [...msgs, { role: 'user', content: text }];
    setMsgs(next);
    setBusy(true);
    try {
      const r = await fetch(`/api/disclosures/${reportId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text }),
      });
      const d = (await r.json()) as ChatResponse & { message?: string };
      if (!r.ok) {
        setErr(d.message ?? '生成失败');
      } else {
        setMsgs([
          ...next,
          {
            role: 'assistant',
            content: d.answer,
            citations: d.citations,
            fallback: d.fallback,
            model: d.model,
          },
        ]);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : '网络错误');
    } finally {
      setBusy(false);
      requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }));
    }
  }, [busy, msgs, q, reportId]);

  return (
    <Section title="问答">
      <div ref={scrollRef} className="max-h-64 space-y-2 overflow-auto" aria-live="polite">
        {msgs.length === 0 && (
          <p className="text-xs text-ink-soft">支持「营收」「经营现金流」「同比」等问题，回答附页码引用。</p>
        )}
        {msgs.map((m, i) => (
          <div
            key={i}
            className={`rounded-lg p-2 text-sm ${m.role === 'user' ? 'bg-accent-soft/40 ml-4' : 'bg-surface-muted mr-4'}`}
          >
            {m.role === 'assistant' ? (
              <div className="markdown-answer leading-relaxed">
                <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
                  {m.content}
                </ReactMarkdown>
              </div>
            ) : (
              <div className="whitespace-pre-wrap leading-relaxed">{m.content}</div>
            )}
            {m.citations && m.citations.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {m.citations.map((c, j) => (
                  <CitationChip key={j} citation={c} onCite={onCite} />
                ))}
              </div>
            )}
            {m.fallback && (
              <p className="mt-1 text-[10px] text-ink-soft">（未接入 LLM，使用抽取式回答）</p>
            )}
            {!m.fallback && m.model && (
              <p className="mt-1 text-[10px] text-ink-soft">模型：{m.model}</p>
            )}
          </div>
        ))}
        {err && <p className="text-xs text-rose-600">{err}</p>}
      </div>
      <form
        className="mt-2 flex gap-1"
        onSubmit={(e) => {
          e.preventDefault();
          void ask();
        }}
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="例如：本期营业收入与上年同期相比如何？"
          aria-label="输入问题"
          disabled={busy}
          maxLength={500}
          className="flex-1 rounded-md border border-line bg-surface px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-accent disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={busy || !q.trim()}
          className="rounded-md border border-line bg-accent px-3 py-1.5 text-sm text-white hover:opacity-90 disabled:opacity-50"
        >
          提问
        </button>
      </form>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// 共用：引用 chip
// ---------------------------------------------------------------------------

function CitationChip({ citation, onCite }: { citation: Citation; onCite: CitationJump }) {
  const preview = citation.text.length > 30 ? citation.text.slice(0, 30) + '…' : citation.text;
  return (
    <button
      type="button"
      onClick={() => onCite(citation.page, citation.text)}
      className="rounded-full border border-accent/40 bg-accent-soft/50 px-2 py-0.5 text-[11px] text-accent hover:bg-accent-soft focus:outline-none focus:ring-2 focus:ring-accent"
      aria-label={`跳转到第 ${citation.page} 页：${preview}`}
      title={citation.text}
    >
      p.{citation.page} · {preview}
    </button>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section aria-label={title}>
      <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-soft">{title}</h3>
      <div className="rounded-lg border border-line p-3">{children}</div>
    </section>
  );
}
