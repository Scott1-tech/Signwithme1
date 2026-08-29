import type { PageIssue } from '../types/comparison';
import type { BBox } from '../types/field';

interface Props {
  issues: PageIssue[];
  /** CSS pixels per PDF point, from the viewer. Without it, highlights drift
   *  away from the page as soon as the user zooms. */
  scale: number;
  activeFieldId?: string | null;
  onSelect?: (issue: PageIssue) => void;
}

function toPixels(bbox: BBox, scale: number) {
  return {
    left: bbox.x * scale,
    top: bbox.y * scale,
    width: bbox.width * scale,
    height: bbox.height * scale,
  };
}

export function FieldHighlighter({ issues, scale, activeFieldId, onSelect }: Props) {
  // Only issues carrying coordinates can be drawn; the rest live in the sidebar.
  const positioned = issues.filter((issue) => issue.bbox !== null);

  return (
    <>
      {positioned.map((issue) => {
        const box = toPixels(issue.bbox as BBox, scale);
        const isActive = activeFieldId != null && issue.fieldId === activeFieldId;
        return (
          <button
            key={issue.key}
            type="button"
            className={`highlight highlight--${issue.severity}${isActive ? ' highlight--active' : ''}`}
            style={box}
            title={`${issue.label}: ${issue.detail}`}
            onClick={(event) => {
              event.stopPropagation();
              onSelect?.(issue);
            }}
          >
            <span className="highlight__label">{issue.label}</span>
          </button>
        );
      })}
    </>
  );
}
