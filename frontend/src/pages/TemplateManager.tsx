import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { templatesApi } from '../api/templates';
import type { Template, TemplateDetail } from '../types/template';

export function TemplateManager() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selected, setSelected] = useState<TemplateDetail | null>(null);
  const [name, setName] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    setTemplates(await templatesApi.list());
  }, []);

  useEffect(() => {
    void refresh().catch((cause) =>
      setError(cause instanceof Error ? cause.message : 'Failed to load templates'),
    );
  }, [refresh]);

  // Detection runs in a worker, so the list is polled while anything is
  // still processing rather than leaving the admin to refresh by hand.
  useEffect(() => {
    const processing = templates.some((template) => template.status === 'processing');
    if (!processing) {
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = null;
      return;
    }
    pollRef.current = window.setInterval(() => void refresh(), 3000);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [templates, refresh]);

  const upload = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await templatesApi.upload(file, name || file.name);
      setName('');
      setFile(null);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Upload failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="page">
      <header className="page__header">
        <h1>Templates</h1>
      </header>

      <form className="card" onSubmit={upload}>
        <h2>Upload a blank template</h2>
        <p className="hint">
          Field detection runs in the background; the template becomes available for contracts once
          it reports <strong>ready</strong>.
        </p>
        <label className="field">
          <span>Template name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Driver contract" />
        </label>
        <label className="field">
          <span>PDF file</span>
          <input
            type="file"
            accept="application/pdf"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            required
          />
        </label>
        {error && <p className="alert alert--error">{error}</p>}
        <button type="submit" className="button button--primary" disabled={busy || !file}>
          {busy ? 'Uploading…' : 'Upload and analyse'}
        </button>
      </form>

      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Status</th>
            <th>Pages</th>
            <th>Fields</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {templates.map((template) => (
            <tr key={template.id}>
              <td>{template.name}</td>
              <td>
                <span
                  className={`badge badge--${
                    template.status === 'ready' ? 'good' : template.status === 'failed' ? 'bad' : 'neutral'
                  }`}
                >
                  {template.status}
                </span>
                {template.error_message && (
                  <span className="hint hint--error"> {template.error_message}</span>
                )}
              </td>
              <td>{template.page_count}</td>
              <td>
                <button
                  type="button"
                  className="button button--link"
                  onClick={() =>
                    templatesApi.get(template.id).then(setSelected).catch(() => setSelected(null))
                  }
                >
                  Inspect
                </button>
              </td>
              <td>
                <button
                  type="button"
                  className="button button--link"
                  onClick={() => templatesApi.reanalyze(template.id).then(() => refresh())}
                >
                  Re-analyse
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {selected && (
        <div className="card">
          <h2>
            {selected.name} · {selected.field_schema.field_count} detected fields
          </h2>
          <p className="hint">
            Detection is good, not perfect. A misplaced signature box is the difference between a
            signature landing on the line or beside it — correct coordinates here.
          </p>
          {selected.field_schema.pages.map((page) => (
            <details key={page.page_number}>
              <summary>
                Page {page.page_number} — {page.fields.length} fields
              </summary>
              <table className="table table--compact">
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>Type</th>
                    <th>Required</th>
                    <th>x, y</th>
                    <th>w × h</th>
                  </tr>
                </thead>
                <tbody>
                  {page.fields.map((field) => (
                    <tr key={field.field_id}>
                      <td>
                        <code>{field.field_id}</code>
                        <div className="hint">{field.label}</div>
                      </td>
                      <td>{field.field_type}</td>
                      <td>{field.required ? 'yes' : 'no'}</td>
                      <td>
                        {field.bbox.x.toFixed(0)}, {field.bbox.y.toFixed(0)}
                      </td>
                      <td>
                        {field.bbox.width.toFixed(0)} × {field.bbox.height.toFixed(0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          ))}
        </div>
      )}
    </section>
  );
}
