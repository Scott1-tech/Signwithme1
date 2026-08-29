import { useCallback, useEffect, useRef, useState } from 'react';
import * as pdfjs from 'pdfjs-dist';
import type { PDFDocumentProxy } from 'pdfjs-dist';

// Bundled worker: no CDN fetch, so the viewer works offline and behind a proxy.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

export interface PdfViewerState {
  canvasRef: React.RefObject<HTMLCanvasElement>;
  pageCount: number;
  currentPage: number;
  setCurrentPage: (page: number) => void;
  /** CSS pixels per PDF point. Overlays MUST multiply by this or they drift
   *  the moment the user zooms. */
  scale: number;
  setScale: (scale: number) => void;
  /** Rendered size in CSS pixels, for sizing the highlight layer. */
  size: { width: number; height: number };
  rotation: number;
  loading: boolean;
  error: string | null;
  zoomIn: () => void;
  zoomOut: () => void;
  fitToWidth: (containerWidth: number) => void;
}

export function usePdfViewer(source: ArrayBuffer | null): PdfViewerState {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const documentRef = useRef<PDFDocumentProxy | null>(null);
  const renderTaskRef = useRef<{ cancel: () => void } | null>(null);

  const [pageCount, setPageCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1.25);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [rotation, setRotation] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!source) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    // pdf.js transfers the buffer, so hand it a copy the caller can reuse.
    const task = pdfjs.getDocument({ data: source.slice(0) });
    task.promise
      .then((doc) => {
        if (cancelled) {
          void doc.destroy();
          return;
        }
        documentRef.current = doc;
        setPageCount(doc.numPages);
        setCurrentPage((page) => Math.min(page, doc.numPages));
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : 'Failed to open PDF');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      void task.destroy();
      documentRef.current = null;
    };
  }, [source]);

  useEffect(() => {
    const doc = documentRef.current;
    const canvas = canvasRef.current;
    if (!doc || !canvas || pageCount === 0) return;

    let cancelled = false;
    void (async () => {
      try {
        const page = await doc.getPage(Math.min(currentPage, doc.numPages));
        if (cancelled) return;

        const viewport = page.getViewport({ scale });
        const context = canvas.getContext('2d');
        if (!context) return;

        // Render at device resolution, present at CSS size, so overlay maths
        // stays in CSS pixels regardless of screen density.
        const ratio = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * ratio);
        canvas.height = Math.floor(viewport.height * ratio);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        context.setTransform(ratio, 0, 0, ratio, 0, 0);

        renderTaskRef.current?.cancel();
        const renderTask = page.render({ canvasContext: context, viewport });
        renderTaskRef.current = renderTask;
        await renderTask.promise;

        if (!cancelled) {
          setSize({ width: viewport.width, height: viewport.height });
          setRotation(page.rotate ?? 0);
        }
      } catch (cause) {
        const name = (cause as { name?: string }).name;
        if (!cancelled && name !== 'RenderingCancelledException') {
          setError(cause instanceof Error ? cause.message : 'Failed to render page');
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [currentPage, scale, pageCount]);

  const zoomIn = useCallback(() => setScale((value) => Math.min(value + 0.25, 4)), []);
  const zoomOut = useCallback(() => setScale((value) => Math.max(value - 0.25, 0.5)), []);

  const fitToWidth = useCallback(
    (containerWidth: number) => {
      const doc = documentRef.current;
      if (!doc || containerWidth <= 0) return;
      void doc.getPage(currentPage).then((page) => {
        const unscaled = page.getViewport({ scale: 1 });
        setScale(Math.max(0.5, Math.min((containerWidth - 32) / unscaled.width, 4)));
      });
    },
    [currentPage],
  );

  return {
    canvasRef,
    pageCount,
    currentPage,
    setCurrentPage,
    scale,
    setScale,
    size,
    rotation,
    loading,
    error,
    zoomIn,
    zoomOut,
    fitToWidth,
  };
}
