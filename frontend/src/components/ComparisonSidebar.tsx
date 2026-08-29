import { useMemo, useState } from 'react';
import { ComplianceBadge } from './ComplianceBadge';
import { ProgressBar } from './ProgressBar';
import type { ComparisonResult, IssueKind, PageIssue } from '../types/comparison';

interface Props {
  result: ComparisonResult | null;
  issues: PageIssue[];
  currentPage: number;
  processing?: boolean;
  onNavigateToIssue: (issue: PageIssue) => void;
  activeFieldId?: string | null;
}

const KIND_LABELS: Record<IssueKind, string> = {
  missing: 'Missing required',
  inconsistency: 'Inconsistent',
  fmcsa: 'FMCSA',
  warning: 'Warning',
};

const KIND_ORDER: IssueKind[] = ['fmcsa', 'missing', 'inconsistency', 'warning'];

export function ComparisonSidebar({
  result,
  issues,
  currentPage,
  processing,
  onNavigateToIssue,
  activeFieldId,
}: Props) {
  const [scope, setScope] = useState<'page' | 'all'>('all');

  const visible = useMemo(
    () => (scope === 'page' ? issues.filter((issue) => issue.page === currentPage) : issues),
    [issues, scope, currentPage],
  );

  const grouped = useMemo(() => {
    const map = new Map<IssueKind, PageIssue[]>();
    KIND_ORDER.forEach((kind) => map.set(kind, []));
    visible.forEach((issue) => map.get(issue.kind)?.push(issue));
    return map;
  }, [visible]);

  return (
    <aside className="sidebar">
      <header className="sidebar__header">
        <h2>Review</h2>
        <ComplianceBadge result={result} processing={processing} />
      </header>

      {result && (
        <div className="sidebar__summary">
          <ProgressBar percentage={result.completion_percentage} />
          <p className="sidebar__counts">
            {result.filled_count} of {result.field_count} fields filled
          </p>
        </div>
      )}

      <div className="sidebar__scope">
        <button
          type="button"
          className={scope === 'all' ? 'chip chip--active' : 'chip'}
          onClick={() => setScope('all')}
        >
          All pages ({issues.length})
        </button>
        <button
          type="button"
          className={scope === 'page' ? 'chip chip--active' : 'chip'}
          onClick={() => setScope('page')}
        >
          This page ({issues.filter((issue) => issue.page === currentPage).length})
        </button>
      </div>

      {visible.length === 0 && (
        <p className="sidebar__empty">
          {processing ? 'Analysing the document…' : 'No issues in this view.'}
        </p>
      )}

      {KIND_ORDER.map((kind) => {
        const group = grouped.get(kind) ?? [];
        if (group.length === 0) return null;
        return (
          <section key={kind} className="sidebar__group">
            <h3 className="sidebar__group-title">
              {KIND_LABELS[kind]} <span className="sidebar__group-count">{group.length}</span>
            </h3>
            <ul className="issue-list">
              {group.map((issue) => (
                <li key={issue.key}>
                  <button
                    type="button"
                    className={`issue issue--${issue.severity}${
                      activeFieldId && issue.fieldId === activeFieldId ? ' issue--active' : ''
                    }`}
                    onClick={() => onNavigateToIssue(issue)}
                  >
                    <span className="issue__label">{issue.label}</span>
                    <span className="issue__detail">{issue.detail}</span>
                    <span className="issue__meta">
                      {issue.page ? `Page ${issue.page}` : 'Document-wide'}
                      {issue.bbox ? '' : ' · no highlight'}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </aside>
  );
}
