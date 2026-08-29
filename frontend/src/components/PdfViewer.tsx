import { useEffect, useRef, type ReactNode } from 'react';
import type { PdfViewerState } from '../hooks/usePdfViewer';
import type { BBox } from '../types/field';

interface Props {
  viewer: PdfViewerState;
  /** Rendered inside the overlay layer, aligned to the page. */
  children?: ReactNode;
  /** Click-to-place mode. Receives PDF-point coordinates, top-left origin --
   *  the same space the API and the PDF builder use. */
  interactive?: boolean;
  onCanvasClick?: (page: number, point: { x: number; y: number }, suggested: BBox) => void;
  placementSize?: { width: number; height: number };
}

export function PdfViewer({
  viewer,
  children,
  interactive = false,
  onCanvasClick,
  placementSize = { width: 180, height: 34 },
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { canvasRef, scale, size, currentPage, pageCount, loading, error } = viewer;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    viewer.fitToWidth(container.clientWidth);
    // Fit once per document; the user's zoom choice is theirs to keep afterwards.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageCount]);

  const handleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!interactive || !onCanvasClick) return;
    const rect = event.currentTarget.getBoundingClientRect();
    // CSS pixels back to PDF points: the single inverse of the render scale.
    const x = (event.clientX - rect.left) / scale;
    const y = (event.clientY - rect.top) / scale;
    onCanvasClick(currentPage, { x, y }, {
      x: Math.max(x - placementSize.width / 2, 0),
      y: Math.max(y - placementSize.height / 2, 0),
      width: placementSize.width,
      height: placementSize.height,
    });
  };

  return (
    <div className="pdf-viewer" ref={containerRef}>
      <div className="pdf-toolbar">
        <button type="button" onClick={() => viewer.setCurrentPage(Math.max(1, currentPage - 1))}
                disabled={currentPage <= 1}>
          ‹ Prev
        </button>
        <span className="pdf-toolbar__page">
          Page {currentPage} of {pageCount || '–'}
        </span>
        <button type="button"
                onClick={() => viewer.setCurrentPage(Math.min(pageCount, currentPage + 1))}
                disabled={currentPage >= pageCount}>
          Next ›
        </button>
        <span className="pdf-toolbar__spacer" />
        <button type="button" onClick={viewer.zoomOut}>−</button>
        <span className="pdf-toolbar__zoom">{Math.round(scale * 100)}%</span>
        <button type="button" onClick={viewer.zoomIn}>+</button>
        <button type="button"
                onClick={() => viewer.fitToWidth(containerRef.current?.clientWidth ?? 0)}>
          Fit
        </button>
      </div>

      <div className="pdf-stage">
        {loading && <p className="pdf-status">Loading document…</p>}
        {error && <p className="pdf-status pdf-status--error">{error}</p>}
        <div
          className={`pdf-page${interactive ? ' pdf-page--interactive' : ''}`}
          style={{ width: size.width || undefined, height: size.height || undefined }}
          onClick={handleClick}
        >
          <canvas ref={canvasRef} className="pdf-canvas" />
          <div className="pdf-overlay" style={{ width: size.width, height: size.height }}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
