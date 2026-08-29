import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ComparisonSidebar } from '../components/ComparisonSidebar';
import { FieldHighlighter } from '../components/FieldHighlighter';
import { PdfViewer } from '../components/PdfViewer';
import { contractsApi } from '../api/contracts';
import { fetchPdf } from '../api/client';
import { useAuth } from '../hooks/useAuth';
import { useComparison } from '../hooks/useComparison';
import { usePdfViewer } from '../hooks/usePdfViewer';
import type { PageIssue } from '../types/comparison';

export function ReviewPage() {
  const { contractId } = useParams<{ contractId: string }>();
  const navigate = useNavigate();
  const { isAtLeast } = useAuth();
  const { contract, result, issues, issuesForPage, processing, error, refresh } =
    useComparison(contractId);

  const [source, setSource] = useState<ArrayBuffer | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeFieldId, setActiveFieldId] = useState<string | null>(null);
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

  const viewer = usePdfViewer(source);

  useEffect(() => {
    if (!contractId) return;
    fetchPdf(`/api/contracts/${contractId}/file`)
      .then(setSource)
      .catch((cause) => setLoadError(cause instanceof Error ? cause.message : 'Failed to load PDF'));
  }, [contractId]);

  const goToIssue = useCallback(
    (issue: PageIssue) => {
      if (issue.page) viewer.setCurrentPage(issue.page);
      setActiveFieldId(issue.fieldId);
    },
    [viewer],
  );

  const decide = async (decision: 'approved' | 'rejected') => {
    if (!contractId) return;
    setBusy(true);
    try {
      await contractsApi.submitReview(contractId, decision, notes || undefined);
      await refresh();
      if (decision === 'approved') navigate(`/contracts/${contractId}/sign`);
    } catch (cause) {
      setLoadError(cause instanceof Error ? cause.message : 'Review failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="review">
      <div className="review__document">
        {loadError && <p className="alert alert--error">{loadError}</p>}
        {error && <p className="alert alert--error">{error}</p>}
        <PdfViewer viewer={viewer}>
          <FieldHighlighter
            issues={issuesForPage(viewer.currentPage)}
            scale={viewer.scale}
            activeFieldId={activeFieldId}
            onSelect={(issue) => setActiveFieldId(issue.fieldId)}
          />
        </PdfViewer>
      </div>

      <div className="review__panel">
        <ComparisonSidebar
          result={result}
          issues={issues}
          currentPage={viewer.currentPage}
          processing={processing}
          onNavigateToIssue={goToIssue}
          activeFieldId={activeFieldId}
        />

        {isAtLeast('reviewer') && contract && contract.review_status === 'pending' && (
          <div className="review__decision card">
            <h3>Decision</h3>
            <textarea
              className="field__textarea"
              placeholder="Review notes (optional)"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
            {result && !result.can_sign && (
              <p className="hint hint--error">
                Approval is blocked while critical issues remain. Correct the fields and re-run the
                comparison.
              </p>
            )}
            <div className="review__actions">
              <button
                type="button"
                className="button button--ghost"
                disabled={busy}
                onClick={() => decide('rejected')}
              >
                Reject
              </button>
              <button
                type="button"
                className="button button--primary"
                disabled={busy || !result?.can_sign}
                onClick={() => decide('approved')}
              >
                Approve for signing
              </button>
            </div>
          </div>
        )}

        {contract && contract.review_status === 'approved' && contract.status !== 'completed' && (
          <div className="card">
            <p>Approved for signing.</p>
            <button
              type="button"
              className="button button--primary"
              onClick={() => navigate(`/contracts/${contract.id}/sign`)}
            >
              Continue to signing
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
