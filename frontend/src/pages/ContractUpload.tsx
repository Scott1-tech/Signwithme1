import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { contractsApi } from '../api/contracts';
import { templatesApi } from '../api/templates';
import type { Template } from '../types/template';

export function ContractUpload() {
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templateId, setTemplateId] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [contractorName, setContractorName] = useState('');
  const [contractorEmail, setContractorEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    templatesApi
      .list()
      .then((all) => {
        // Only a fully analysed template can be compared against.
        const ready = all.filter((template) => template.status === 'ready');
        setTemplates(ready);
        if (ready.length > 0) setTemplateId(ready[0].id);
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : 'Failed to load templates'));
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file || !templateId) return;
    setBusy(true);
    setError(null);
    try {
      const result = await contractsApi.upload(templateId, file, contractorName, contractorEmail);
      navigate(`/contracts/${result.contract_id}/review`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Upload failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="page">
      <header className="page__header">
        <h1>Upload a contract</h1>
      </header>

      <form className="card" onSubmit={submit}>
        <label className="field">
          <span>Template</span>
          <select value={templateId} onChange={(event) => setTemplateId(event.target.value)} required>
            {templates.length === 0 && <option value="">No analysed templates available</option>}
            {templates.map((template) => (
              <option key={template.id} value={template.id}>
                {template.name}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Contractor name</span>
          <input value={contractorName} onChange={(event) => setContractorName(event.target.value)} />
        </label>

        <label className="field">
          <span>Contractor email</span>
          <input
            type="email"
            value={contractorEmail}
            onChange={(event) => setContractorEmail(event.target.value)}
          />
        </label>

        <label className="field">
          <span>Completed contract (PDF)</span>
          <input
            type="file"
            accept="application/pdf"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            required
          />
        </label>

        {error && <p className="alert alert--error">{error}</p>}

        <button type="submit" className="button button--primary" disabled={busy || !file || !templateId}>
          {busy ? 'Uploading…' : 'Upload and compare'}
        </button>
      </form>
    </section>
  );
}
