'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { DisclosureDetail, TYPE_LABELS } from '@fr/shared';
import { PdfViewer, PdfViewerHandle } from './PdfViewer';
import { TocPanel } from './TocPanel';
import { AiPanel } from './AiPanel';

interface Props {
  detail: DisclosureDetail;
  pdfUrl: string;
  returnTo: string;
}

// 阅读页三栏布局（§8.1）：目录 / PDF / AI 面板；桌面三栏，移动端 AI 收为底部抽屉
export function ReaderPage({ detail, pdfUrl, returnTo }: Props) {
  const viewerRef = useRef<PdfViewerHandle>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [numPages, setNumPages] = useState(0);
  const [aiOpen, setAiOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [searchMsg, setSearchMsg] = useState<string | null>(null);
  const [readerMode, setReaderMode] = useState<'native' | 'smart'>('native');
  const [aiPanelWidth, setAiPanelWidth] = useState(420);
  const [smartOpened, setSmartOpened] = useState(false);

  useEffect(() => {
    const saved = Number(window.localStorage.getItem('financial-reader-ai-width'));
    if (Number.isFinite(saved) && saved >= 340 && saved <= 720) {
      setAiPanelWidth(saved);
    }
    const savedPage = Number(
      window.sessionStorage.getItem(`financial-reader-page:${detail.id}`),
    );
    if (Number.isInteger(savedPage) && savedPage > 0) {
      setCurrentPage(savedPage);
    }
    const savedMode = window.sessionStorage.getItem(
      `financial-reader-mode:${detail.id}`,
    );
    if (savedMode === 'smart') {
      setReaderMode('smart');
      setSmartOpened(true);
    }
  }, [detail.id]);

  const rememberPage = useCallback((page: number) => {
    const safePage = Math.max(1, Math.round(page));
    setCurrentPage(safePage);
    window.sessionStorage.setItem(
      `financial-reader-page:${detail.id}`,
      String(safePage),
    );
  }, [detail.id]);

  const changeReaderMode = (mode: 'native' | 'smart') => {
    setReaderMode(mode);
    if (mode === 'smart') setSmartOpened(true);
    window.sessionStorage.setItem(`financial-reader-mode:${detail.id}`, mode);
  };

  const resizeAiPanel = (nextWidth: number) => {
    const maxWidth = Math.min(720, Math.floor(window.innerWidth * 0.6));
    setAiPanelWidth(Math.max(340, Math.min(maxWidth, Math.round(nextWidth))));
  };

  const startAiPanelResize = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = aiPanelWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const onMove = (moveEvent: PointerEvent) => {
      resizeAiPanel(startWidth + startX - moveEvent.clientX);
    };
    const onUp = (upEvent: PointerEvent) => {
      const maxWidth = Math.min(720, Math.floor(window.innerWidth * 0.6));
      const width = Math.max(
        340,
        Math.min(maxWidth, Math.round(startWidth + startX - upEvent.clientX)),
      );
      setAiPanelWidth(width);
      window.localStorage.setItem('financial-reader-ai-width', String(width));
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp, { once: true });
  };

  const jump = (page: number) => {
    rememberPage(page);
    if (readerMode === 'smart') viewerRef.current?.scrollToPage(page);
  };

  useEffect(() => {
    if (readerMode !== 'smart') return;
    const timer = window.setTimeout(() => viewerRef.current?.scrollToPage(currentPage), 100);
    return () => window.clearTimeout(timer);
  }, [readerMode]);

  // 引用跳页+高亮（§7.3 / §8.2）：先滚到引用页，再在该页文本层高亮命中片段
  const onCite = (page: number, text: string) => {
    rememberPage(page);
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
          <a href={returnTo} className="text-xs text-accent hover:underline">
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
                changeReaderMode('native');
                setAiOpen(false);
              }}
              className={`rounded px-2.5 py-1 text-sm ${readerMode === 'native' ? 'bg-accent text-white' : 'hover:bg-accent-soft'}`}
            >
              原生阅读
            </button>
            <button
              type="button"
              onClick={() => changeReaderMode('smart')}
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
              onPageChange={rememberPage}
              onNumPages={setNumPages}
            />
          )}
        </main>

        {smartOpened && (
          <aside
            className={
              readerMode === 'smart'
                ? 'relative hidden shrink-0 border-l border-line bg-surface lg:block'
                : 'hidden'
            }
            style={{ width: aiPanelWidth }}
          >
            <div
              role="separator"
              aria-label="调整 AI 面板宽度"
              aria-orientation="vertical"
              aria-valuemin={340}
              aria-valuemax={720}
              aria-valuenow={aiPanelWidth}
              tabIndex={0}
              onPointerDown={startAiPanelResize}
              onDoubleClick={() => {
                setAiPanelWidth(420);
                window.localStorage.setItem('financial-reader-ai-width', '420');
              }}
              onKeyDown={(event) => {
                if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
                event.preventDefault();
                const requestedWidth =
                  aiPanelWidth + (event.key === 'ArrowLeft' ? 24 : -24);
                const maxWidth = Math.min(720, Math.floor(window.innerWidth * 0.6));
                const width = Math.max(340, Math.min(maxWidth, requestedWidth));
                resizeAiPanel(width);
                window.localStorage.setItem(
                  'financial-reader-ai-width',
                  String(width),
                );
              }}
              className="absolute inset-y-0 -left-1 z-20 w-2 cursor-col-resize touch-none outline-none after:absolute after:inset-y-0 after:left-1/2 after:w-px after:bg-transparent hover:after:bg-accent focus-visible:after:bg-accent"
            />
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
