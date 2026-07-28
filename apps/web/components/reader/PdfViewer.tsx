'use client';

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import './textLayer.css';

export interface PdfViewerHandle {
  scrollToPage: (page: number) => void;
  highlightText: (query: string) => Promise<number | null>;
  clearHighlights: () => void;
}

interface Props {
  url: string;
  initialPage?: number;
  onPageChange?: (page: number) => void;
  onNumPages?: (pages: number) => void;
}

const BASE_SCALE = 1.45;
const MIN_OUTPUT_SCALE = 1.5;

type Point = { x: number; y: number };
type PdfAnnotation =
  | { type: 'draw'; points: Point[] }
  | { type: 'signature'; x: number; y: number; text: string }
  | { type: 'image'; x: number; y: number; src: string };

export const PdfViewer = forwardRef<PdfViewerHandle, Props>(function PdfViewer(
  { url, initialPage = 1, onPageChange, onNumPages },
  ref,
) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const docRef = useRef<PDFDocumentProxy | null>(null);
  const initialPageRef = useRef(initialPage);
  const pageEls = useRef(new Map<number, HTMLDivElement>());
  const rendering = useRef(new Map<number, Promise<void>>());
  const zoomRef = useRef(1);
  const rotationRef = useRef(0);
  const dragRef = useRef<{
    x: number;
    y: number;
    left: number;
    top: number;
  } | null>(null);
  const annotationsRef = useRef(new Map<number, PdfAnnotation[]>());
  const activeStrokeRef = useRef<{ page: number; annotation: PdfAnnotation } | null>(null);
  const signatureTextRef = useRef('');
  const pendingImageRef = useRef('');
  const imageInputRef = useRef<HTMLInputElement>(null);
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(initialPage);
  const [pageInput, setPageInput] = useState(String(initialPage));
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [tool, setTool] = useState<
    'select' | 'hand' | 'draw' | 'signature' | 'image'
  >('select');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const renderPage = useCallback(async (pageNumber: number) => {
    const cached = rendering.current.get(pageNumber);
    if (cached) return cached;
    const wrapper = pageEls.current.get(pageNumber);
    const doc = docRef.current;
    if (!wrapper || !doc || wrapper.dataset.rendered === '1') return;

    const task = (async () => {
      const pdfjs = await import('pdfjs-dist');
      const page = await doc.getPage(pageNumber);
      const viewport = page.getViewport({
        scale: BASE_SCALE * zoomRef.current,
        rotation: rotationRef.current,
      });
      const outputScale = Math.max(window.devicePixelRatio || 1, MIN_OUTPUT_SCALE);

      wrapper.style.width = `${viewport.width}px`;
      wrapper.style.height = `${viewport.height}px`;
      wrapper.innerHTML = '';

      const canvas = document.createElement('canvas');
      canvas.width = Math.ceil(viewport.width * outputScale);
      canvas.height = Math.ceil(viewport.height * outputScale);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      wrapper.appendChild(canvas);

      const context = canvas.getContext('2d');
      if (context) {
        context.imageSmoothingQuality = 'high';
        const scaleX = canvas.width / viewport.width;
        const scaleY = canvas.height / viewport.height;
        await page.render({
          canvasContext: context,
          viewport,
          transform:
            scaleX === 1 && scaleY === 1
              ? undefined
              : [scaleX, 0, 0, scaleY, 0, 0],
        }).promise;
      }

      const textLayer = document.createElement('div');
      textLayer.className = 'textLayer';
      textLayer.style.width = `${viewport.width}px`;
      textLayer.style.height = `${viewport.height}px`;
      wrapper.appendChild(textLayer);
      try {
        const textContent = await page.getTextContent();
        await new pdfjs.TextLayer({
          textContentSource: textContent,
          container: textLayer,
          viewport,
        }).render();
      } catch {
        // 文本层失败不影响 PDF 画面阅读。
      }

      const highlightLayer = document.createElement('div');
      highlightLayer.className = 'highlightLayer';
      wrapper.appendChild(highlightLayer);
      const annotationLayer = document.createElement('div');
      annotationLayer.className = 'annotationLayer';
      wrapper.appendChild(annotationLayer);
      wrapper.dataset.rendered = '1';
      renderAnnotations(pageNumber);
    })().finally(() => rendering.current.delete(pageNumber));

    rendering.current.set(pageNumber, task);
    return task;
  }, []);

  const renderAnnotations = (pageNumber: number) => {
    const wrapper = pageEls.current.get(pageNumber);
    const layer = wrapper?.querySelector<HTMLElement>('.annotationLayer');
    if (!wrapper || !layer) return;
    layer.innerHTML = '';
    const annotations = annotationsRef.current.get(pageNumber) ?? [];
    annotations.forEach((annotation) => {
      if (annotation.type === 'draw') {
        if (annotation.points.length < 2) return;
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', '0 0 1 1');
        svg.setAttribute('preserveAspectRatio', 'none');
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute(
          'd',
          annotation.points
            .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`)
            .join(' '),
        );
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', '#d63333');
        path.setAttribute('stroke-width', '0.0035');
        path.setAttribute('stroke-linecap', 'round');
        path.setAttribute('stroke-linejoin', 'round');
        svg.appendChild(path);
        layer.appendChild(svg);
      } else if (annotation.type === 'signature') {
        const signature = document.createElement('div');
        signature.className = 'pdf-signature';
        signature.style.left = `${annotation.x * 100}%`;
        signature.style.top = `${annotation.y * 100}%`;
        signature.textContent = annotation.text;
        layer.appendChild(signature);
      } else {
        const image = document.createElement('img');
        image.className = 'pdf-image-annotation';
        image.style.left = `${annotation.x * 100}%`;
        image.style.top = `${annotation.y * 100}%`;
        image.src = annotation.src;
        image.alt = '图片批注';
        layer.appendChild(image);
      }
    });
  };

  const clearHighlights = useCallback(() => {
    pageEls.current.forEach((page) => {
      page.querySelectorAll('.pdf-search-hit').forEach((hit) => hit.remove());
    });
  }, []);

  const scrollToPage = useCallback(
    async (page: number) => {
      const target = Math.max(1, Math.min(numPages || 1, page));
      await Promise.all([
        renderPage(target),
        renderPage(Math.max(1, target - 1)),
      ]);
      requestAnimationFrame(() => {
        pageEls.current
          .get(target)
          ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        setCurrentPage(target);
        setPageInput(String(target));
        onPageChange?.(target);
      });
      void renderPage(Math.min(numPages || target, target + 1));
    },
    [numPages, onPageChange, renderPage],
  );

  const highlightText = useCallback(
    async (query: string): Promise<number | null> => {
      clearHighlights();
      const term = query.trim().toLowerCase();
      if (!term) return null;
      for (let page = 1; page <= numPages; page += 1) {
        await renderPage(page);
        const wrapper = pageEls.current.get(page);
        const textLayer = wrapper?.querySelector<HTMLElement>('.textLayer');
        if (!wrapper || !textLayer) continue;
        const spans = Array.from(textLayer.querySelectorAll<HTMLElement>('span'));
        const hit = spans.find((span) =>
          (span.textContent ?? '').toLowerCase().includes(term),
        );
        if (!hit) continue;
        const hitRect = hit.getBoundingClientRect();
        const pageRect = wrapper.getBoundingClientRect();
        const marker = document.createElement('div');
        marker.className = 'pdf-search-hit';
        marker.style.left = `${hitRect.left - pageRect.left}px`;
        marker.style.top = `${hitRect.top - pageRect.top}px`;
        marker.style.width = `${hitRect.width}px`;
        marker.style.height = `${hitRect.height}px`;
        wrapper.querySelector('.highlightLayer')?.appendChild(marker);
        await scrollToPage(page);
        return page;
      }
      return null;
    },
    [clearHighlights, numPages, renderPage, scrollToPage],
  );

  useImperativeHandle(ref, () => ({
    scrollToPage: (page) => void scrollToPage(page),
    highlightText,
    clearHighlights,
  }));

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const pdfjs = await import('pdfjs-dist');
        pdfjs.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.mjs';
        const doc = await pdfjs.getDocument({ url }).promise;
        if (disposed) {
          await doc.destroy();
          return;
        }
        docRef.current = doc;
        setNumPages(doc.numPages);
        onNumPages?.(doc.numPages);
        setLoading(false);
        window.setTimeout(() => {
          const target = Math.max(
            1,
            Math.min(doc.numPages, initialPageRef.current),
          );
          void renderPage(target).then(() => {
            pageEls.current
              .get(target)
              ?.scrollIntoView({ behavior: 'auto', block: 'start' });
            onPageChange?.(target);
          });
        }, 0);
      } catch (reason) {
        if (!disposed) {
          setError(
            reason instanceof Error ? reason.message : 'PDF.js 阅读器加载失败',
          );
          setLoading(false);
        }
      }
    })();
    return () => {
      disposed = true;
      void docRef.current?.destroy();
      docRef.current = null;
      rendering.current.clear();
    };
  }, [onNumPages, onPageChange, renderPage, url]);

  useEffect(() => {
    zoomRef.current = zoom;
    rotationRef.current = rotation;
    rendering.current.clear();
    pageEls.current.forEach((page) => {
      page.dataset.rendered = '0';
      page.innerHTML = '';
      page.style.width = '';
      page.style.height = '';
    });
    void renderPage(currentPage);
  }, [renderPage, rotation, zoom]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container || numPages === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            void renderPage(Number((entry.target as HTMLElement).dataset.page));
          }
        });
      },
      { root: container, rootMargin: '600px 0px' },
    );
    pageEls.current.forEach((page) => observer.observe(page));
    return () => observer.disconnect();
  }, [numPages, renderPage]);

  const handleScroll = () => {
    const container = scrollRef.current;
    if (!container) return;
    let current = 1;
    let nearest = Number.POSITIVE_INFINITY;
    pageEls.current.forEach((element, page) => {
      const distance = Math.abs(element.offsetTop - container.scrollTop);
      if (distance < nearest) {
        nearest = distance;
        current = page;
      }
    });
    setCurrentPage(current);
    setPageInput(String(current));
    onPageChange?.(current);
  };

  const changeZoom = (next: number) => {
    setZoom(Math.max(0.5, Math.min(3, next)));
  };

  const fit = async (mode: 'width' | 'page') => {
    const doc = docRef.current;
    const container = scrollRef.current;
    if (!doc || !container) return;
    const page = await doc.getPage(currentPage);
    const base = page.getViewport({ scale: BASE_SCALE, rotation });
    const widthScale = Math.max(0.5, (container.clientWidth - 36) / base.width);
    const heightScale = Math.max(0.5, (container.clientHeight - 36) / base.height);
    changeZoom(mode === 'width' ? widthScale : Math.min(widthScale, heightScale));
  };

  const submitPage = () => {
    const page = Number(pageInput);
    if (Number.isFinite(page)) void scrollToPage(page);
    else setPageInput(String(currentPage));
  };

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    const container = scrollRef.current;
    if (!container) return;
    if (tool === 'hand') {
      dragRef.current = {
        x: event.clientX,
        y: event.clientY,
        left: container.scrollLeft,
        top: container.scrollTop,
      };
      event.currentTarget.setPointerCapture(event.pointerId);
      return;
    }
    if (!['draw', 'signature', 'image'].includes(tool)) return;
    const wrapper = (event.target as HTMLElement).closest<HTMLElement>(
      '.pdf-page-wrapper',
    );
    if (!wrapper) return;
    const page = Number(wrapper.dataset.page);
    const rect = wrapper.getBoundingClientRect();
    const point = {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    };
    const annotations = annotationsRef.current.get(page) ?? [];
    if (tool === 'draw') {
      const annotation: PdfAnnotation = { type: 'draw', points: [point] };
      annotations.push(annotation);
      annotationsRef.current.set(page, annotations);
      activeStrokeRef.current = { page, annotation };
      event.currentTarget.setPointerCapture(event.pointerId);
    } else if (tool === 'signature' && signatureTextRef.current) {
      annotations.push({
        type: 'signature',
        x: point.x,
        y: point.y,
        text: signatureTextRef.current,
      });
      annotationsRef.current.set(page, annotations);
    } else if (tool === 'image' && pendingImageRef.current) {
      annotations.push({
        type: 'image',
        x: point.x,
        y: point.y,
        src: pendingImageRef.current,
      });
      annotationsRef.current.set(page, annotations);
    }
    renderAnnotations(page);
    event.preventDefault();
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const container = scrollRef.current;
    const drag = dragRef.current;
    if (container && drag) {
      container.scrollLeft = drag.left - (event.clientX - drag.x);
      container.scrollTop = drag.top - (event.clientY - drag.y);
      return;
    }
    const stroke = activeStrokeRef.current;
    if (!stroke || stroke.annotation.type !== 'draw') return;
    const wrapper = pageEls.current.get(stroke.page);
    if (!wrapper) return;
    const rect = wrapper.getBoundingClientRect();
    stroke.annotation.points.push({
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    });
    renderAnnotations(stroke.page);
    event.preventDefault();
  };

  const undoAnnotation = () => {
    const annotations = annotationsRef.current.get(currentPage);
    annotations?.pop();
    renderAnnotations(currentPage);
  };

  const clearPageAnnotations = () => {
    annotationsRef.current.delete(currentPage);
    renderAnnotations(currentPage);
  };

  const chooseSignature = () => {
    const text = window.prompt('请输入签名文字', signatureTextRef.current);
    if (!text?.trim()) return;
    signatureTextRef.current = text.trim();
    setTool('signature');
  };

  return (
    <div className="flex h-full flex-col bg-[#f5f6f8]">
      <div
        className="flex h-12 shrink-0 items-center gap-1 border-b border-line bg-white px-2 text-sm"
        role="toolbar"
        aria-label="PDF 阅读工具"
      >
        <button className="pdf-tool-btn" onClick={() => void scrollToPage(currentPage - 1)} disabled={currentPage <= 1} title="上一页">‹</button>
        <input
          className="h-8 w-14 rounded border border-line text-center tabular-nums"
          value={pageInput}
          onChange={(event) => setPageInput(event.target.value)}
          onBlur={submitPage}
          onKeyDown={(event) => event.key === 'Enter' && submitPage()}
          aria-label="页码"
        />
        <span className="mr-2 tabular-nums text-ink-soft">/ {numPages}</span>
        <button className="pdf-tool-btn" onClick={() => void scrollToPage(currentPage + 1)} disabled={currentPage >= numPages} title="下一页">›</button>
        <span className="mx-1 h-6 border-l border-line" />
        <button className={`pdf-tool-btn ${tool === 'select' ? 'is-active' : ''}`} onClick={() => setTool('select')} title="选择文字">▣</button>
        <button className={`pdf-tool-btn ${tool === 'hand' ? 'is-active' : ''}`} onClick={() => setTool('hand')} title="拖拽页面">✋</button>
        <button className="pdf-tool-btn" onClick={() => changeZoom(zoom - 0.1)} title="缩小">−</button>
        <span className="w-12 text-center tabular-nums">{Math.round(zoom * 100)}%</span>
        <button className="pdf-tool-btn" onClick={() => changeZoom(zoom + 0.1)} title="放大">＋</button>
        <button className="pdf-tool-btn px-2" onClick={() => void fit('width')} title="适合宽度">适宽</button>
        <button className="pdf-tool-btn px-2" onClick={() => void fit('page')} title="适合整页">整页</button>
        <button className="pdf-tool-btn" onClick={() => setRotation((value) => (value + 90) % 360)} title="顺时针旋转">↻</button>
        <span className="mx-1 h-6 border-l border-line" />
        <button className={`pdf-tool-btn ${tool === 'draw' ? 'is-active' : ''}`} onClick={() => setTool('draw')} title="画笔批注">✎</button>
        <button className={`pdf-tool-btn ${tool === 'signature' ? 'is-active' : ''}`} onClick={chooseSignature} title="添加文字签名">签</button>
        <button className={`pdf-tool-btn ${tool === 'image' ? 'is-active' : ''}`} onClick={() => imageInputRef.current?.click()} title="添加图片批注">▧</button>
        <input
          ref={imageInputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = () => {
              pendingImageRef.current = String(reader.result ?? '');
              setTool('image');
            };
            reader.readAsDataURL(file);
            event.target.value = '';
          }}
        />
        <button className="pdf-tool-btn" onClick={undoAnnotation} title="撤销当前页最后一个批注">↶</button>
        <button className="pdf-tool-btn" onClick={clearPageAnnotations} title="清空当前页批注">⌫</button>
        <span className="flex-1" />
        <button className="pdf-tool-btn" onClick={() => window.open(url, '_blank', 'noopener,noreferrer')} title="打印">🖨</button>
        <a className="pdf-tool-btn" href={`${url}${url.includes('?') ? '&' : '?'}download=1`} title="下载" aria-label="下载 PDF">⇩</a>
      </div>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={() => {
          dragRef.current = null;
          activeStrokeRef.current = null;
        }}
        onPointerCancel={() => {
          dragRef.current = null;
          activeStrokeRef.current = null;
        }}
        className={`min-h-0 flex-1 overflow-auto p-4 ${
          tool === 'hand'
            ? 'cursor-grab active:cursor-grabbing select-none'
            : ['draw', 'signature', 'image'].includes(tool)
              ? 'cursor-crosshair select-none'
              : ''
        }`}
        role="region"
        aria-label="PDF 智能阅读区"
      >
      {loading && <p className="rounded bg-white p-3 text-sm">正在加载 PDF…</p>}
      {error && (
        <p className="rounded bg-red-50 p-3 text-sm text-red-700" role="alert">
          智能阅读器加载失败：{error}
        </p>
      )}
      {!loading &&
        !error &&
        Array.from({ length: numPages }, (_, index) => index + 1).map((page) => (
          <div
            key={page}
            data-page={page}
            ref={(element) => {
              if (element) pageEls.current.set(page, element);
              else pageEls.current.delete(page);
            }}
            className="pdf-page-wrapper relative mx-auto mb-3 bg-white shadow"
            style={{ minHeight: 1000 }}
          />
        ))}
      </div>
    </div>
  );
});
