import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { contractsApi } from '../api/contracts';
import type { Contract } from '../types/contract';

const STATUS_TONE: Record<string, string> = {
  completed: 'good',
  signing: 'good',
  analyzed: 'warn',
  reviewing: 'warn',
  parsing: 'neutral',
  uploaded: 'neutral',
  failed: 'bad',
};

export function Dashboard() {
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    contractsApi
      .list()
      .then(setContracts)
      .catch((cause) => setError(cause instanceof Error ? cause.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <section className="page">
      <header className="page__header">
        <h1>Contracts</h1>
        <Link className="button button--primary" to="/contracts/new">
          Upload contract
        </Link>
      </header>

      {error && <p className="alert alert--error">{error}</p>}
      {loading && <p>Loading…</p>}
      {!loading && contracts.length === 0 && (
        <p className="empty">No contracts yet. Upload one to get started.</p>
      )}

      {contracts.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Contractor</th>
              <th>Status</th>
              <th>Review</th>
              <th>Uploaded</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {contracts.map((contract) => (
              <tr key={contract.id}>
                <td>{contract.contractor_name ?? '—'}</td>
                <td>
                  <span className={`badge badge--${STATUS_TONE[contract.status] ?? 'neutral'}`}>
                    {contract.status}
                  </span>
                </td>
                <td>{contract.review_status}</td>
                <td>{new Date(contract.created_at).toLocaleDateString()}</td>
                <td className="table__actions">
                  <Link to={`/contracts/${contract.id}/review`}>Review</Link>
                  {contract.review_status === 'approved' && contract.status !== 'completed' && (
                    <Link to={`/contracts/${contract.id}/sign`}>Sign</Link>
                  )}
                  {contract.status === 'completed' && (
                    <Link to={`/contracts/${contract.id}/final`}>Download</Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
