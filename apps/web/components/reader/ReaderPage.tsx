'use client';

import { useEffect, useRef, useState } from 'react';
import { DisclosureDetail, TYPE_LABELS } from '@fr/shared';
import { PdfViewer, PdfViewerHandle } from './PdfViewer';
import { TocPanel } from './TocPanel';
import { AiPanel } from './AiPanel';

interface Props {
  detail: DisclosureDetail;
  pdfUrl: string;
}

// 阅读页三栏布局（§8.1）：目录 / PDF / AI 面板；桌面三栏，移动端 AI 收为底部抽屉
export function ReaderPage({ detail, pdfUrl }: Props) {
  const viewerRef = useRef<PdfViewerHandle>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [numPages, setNumPages] = useState(0);
  const [aiOpen, setAiOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [searchMsg, setSearchMsg] = useState<string | null>(null);
  const [readerMode, setReaderMode] = useState<'native' | 'smart'>('native');

  const jump = (page: number) => {
    setCurrentPage(page);
    if (readerMode === 'smart') viewerRef.current?.scrollToPage(page);
  };

  useEffect(() => {
    if (readerMode !== 'smart') return;
    const timer = window.setTimeout(() => viewerRef.current?.scrollToPage(currentPage), 100);
    return () => window.clearTimeout(timer);
  }, [readerMode]);

  // 引用跳页+高亮（§7.3 / §8.2）：先滚到引用页，再在该页文本层高亮命中片段
  const onCite = (page: number, text: string) => {
    setCurrentPage(page);
    if (readerMode === 'native') return;
    viewerRef.current?.scrollToPage(page);
    // 等待目标页文本层渲染后再高亮（pdf.js 异步）
    setTimeout(() => {
      void viewerRef.current?.highlightText(text);
    }, 350);
  };

  // 页内查找（W3-3 高亮脚手架演示）：在已渲染页文本层命中并绘制高亮
  const doSearch = async () => {
    const q = search.trim();
    if (!q) {
      viewerRef.current?.clearHighlights();
      setSearchMsg(null);
      return;
    }
    const page = await viewerRef.current?.highlightText(q);
    setSearchMsg(page ? `在「第 ${page} 页」命中` : '未在当前已加载页面找到（可先滚动到目标章节）');
  };

  return (
    <div className="flex h-screen flex-col bg-surface-muted text-ink">
      <header className="flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3">
        <div className="min-w-0">
          <a href="/" className="text-xs text-accent hover:underline">
            ← 返回列表
          </a>
          <h1 className="truncate text-base font-semibold">
            {detail.companyName} · {TYPE_LABELS[detail.type]} · {detail.reportPeriod}
          </h1>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-3">
          <div className="flex rounded-md border border-line bg-surface p-0.5" aria-label="阅读模式">
            <button
              type="button"
              onClick={() => {
                setReaderMode('native');
                setAiOpen(false);
              }}
              className={`rounded px-2.5 py-1 text-sm ${readerMode === 'native' ? 'bg-accent text-white' : 'hover:bg-accent-soft'}`}
            >
              原生阅读
            </button>
            <button
              type="button"
              onClick={() => setReaderMode('smart')}
              className={`rounded px-2.5 py-1 text-sm ${readerMode === 'smart' ? 'bg-accent text-white' : 'hover:bg-accent-soft'}`}
            >
              智能阅读
            </button>
          </div>
          <a
            href={`${pdfUrl}${pdfUrl.includes('?') ? '&' : '?'}download=1`}
            className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-sm hover:bg-accent-soft"
            aria-label="下载当前报告 PDF"
          >
            下载 PDF
          </a>
          {readerMode === 'smart' && <form onSubmit={(e) => { e.preventDefault(); void doSearch(); }} className="flex items-center gap-1">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="页内查找"
              aria-label="页内查找关键词"
              className="w-28 rounded-md border border-line bg-surface px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-accent"
            />
            <button
              type="submit"
              className="rounded-md border border-line px-2.5 py-1.5 text-sm hover:bg-accent-soft"
            >
              查找
            </button>
          </form>}
          {searchMsg && (
            <span className="text-xs text-ink-soft" aria-live="polite">
              {searchMsg}
            </span>
          )}
          <span className="text-sm tabular-nums text-ink-soft" aria-live="polite">
            第 {currentPage}
            {numPages ? ` / ${numPages}` : ''} 页
          </span>
          {readerMode === 'smart' && (
            <button
              type="button"
              onClick={() => setAiOpen((v) => !v)}
              className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-accent-soft lg:hidden"
              aria-expanded={aiOpen}
            >
              AI 助手
            </button>
          )}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <TocPanel toc={detail.toc} currentPage={currentPage} onJump={jump} />

        <main className="min-w-0 flex-1 overflow-hidden">
          {readerMode === 'native' ? (
            <embed
              key={currentPage}
              src={`${pdfUrl}#page=${currentPage}&navpanes=0&toolbar=0&statusbar=0&pagemode=thumbs`}
              type="application/pdf"
              className="h-full w-full bg-[#f5f6f8]"
              aria-label="原生 PDF 阅读器"
            />
          ) : (
            <PdfViewer
              ref={viewerRef}
              url={pdfUrl}
              initialPage={currentPage}
              onPageChange={setCurrentPage}
              onNumPages={setNumPages}
            />
          )}
        </main>

        {readerMode === 'smart' && (
          <aside className="hidden w-[340px] shrink-0 border-l border-line bg-surface lg:block">
            <AiPanel detail={detail} onCite={onCite} />
          </aside>
        )}
      </div>

      {/* 移动端 AI 底部抽屉 */}
      {readerMode === 'smart' && aiOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-label="AI 助手">
          <div className="absolute inset-0 bg-black/40" onClick={() => setAiOpen(false)} />
          <div className="absolute inset-x-0 bottom-0 max-h-[80vh] overflow-auto rounded-t-2xl bg-surface shadow-xl">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <span className="text-sm font-semibold">AI 助手</span>
              <button
                type="button"
                onClick={() => setAiOpen(false)}
                className="rounded-md border border-line px-3 py-1 text-sm"
              >
                关闭
              </button>
            </div>
            <AiPanel detail={detail} onCite={onCite} />
          </div>
        </div>
      )}
    </div>
  );
}
