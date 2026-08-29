import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { DatePicker } from '../components/DatePicker';
import { PdfViewer } from '../components/PdfViewer';
import { SignaturePad } from '../components/SignaturePad';
import { fetchPdf } from '../api/client';
import { contractsApi } from '../api/contracts';
import { signaturesApi } from '../api/signatures';
import { templatesApi } from '../api/templates';
import { useComparison } from '../hooks/useComparison';
import { usePdfViewer } from '../hooks/usePdfViewer';
import type { BBox, FieldRegion } from '../types/field';
import type { DateField, Signature } from '../types/contract';

interface PendingPlacement {
  page: number;
  bbox: BBox;
  fieldId: string | null;
}

export function SignaturePage() {
  const { contractId } = useParams<{ contractId: string }>();
  const navigate = useNavigate();
  const { contract, result } = useComparison(contractId);

  const [source, setSource] = useState<ArrayBuffer | null>(null);
  const [signatureFields, setSignatureFields] = useState<FieldRegion[]>([]);
  const [dateFields, setDateFields] = useState<DateField[]>([]);
  const [signatures, setSignatures] = useState<Signature[]>([]);
  const [pending, setPending] = useState<PendingPlacement | null>(null);
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const viewer = usePdfViewer(source);

  useEffect(() => {
    if (!contractId) return;
    fetchPdf(`/api/contracts/${contractId}/file`)
      .then(setSource)
      .catch((cause) => setError(cause instanceof Error ? cause.message : 'Failed to load PDF'));
    signaturesApi.list(contractId).then(setSignatures).catch(() => undefined);
    contractsApi.dateFields(contractId).then(setDateFields).catch(() => undefined);
  }, [contractId]);

  useEffect(() => {
    if (!contract) return;
    templatesApi
      .fields(contract.template_id)
      .then((schema) =>
        setSignatureFields(
          schema.pages.flatMap((page) =>
            page.fields.filter((field) => field.field_type === 'signature'),
          ),
        ),
      )
      .catch(() => undefined);
  }, [contract]);

  const pageSignatureFields = useMemo(
    () => signatureFields.filter((field) => field.page === viewer.currentPage),
    [signatureFields, viewer.currentPage],
  );

  const signedFieldIds = useMemo(
    () => new Set(signatures.map((signature) => signature.field_id).filter(Boolean) as string[]),
    [signatures],
  );

  const confirmSignature = useCallback(
    async (dataUrl: string) => {
      if (!contractId || !pending) return;
      setBusy(true);
      setError(null);
      try {
        // The canvas produces base64; the server stores the image and keeps a
        // hash, which is what the audit trail records.
        const created = await signaturesApi.place(contractId, {
          page: pending.page,
          bbox: pending.bbox,
          field_id: pending.fieldId,
          image_data: dataUrl,
        });
        setSignatures((current) => [...current, created]);
        setPending(null);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'Could not save the signature');
      } finally {
        setBusy(false);
      }
    },
    [contractId, pending],
  );

  const removeSignature = async (signatureId: string) => {
    if (!contractId) return;
    await signaturesApi.remove(contractId, signatureId);
    setSignatures((current) => current.filter((signature) => signature.id !== signatureId));
  };

  const finalize = async () => {
    if (!contractId) return;
    setBusy(true);
    setError(null);
    try {
      // Dates are placed at the template's own date-field coordinates, paired
      // with each signature at detection time -- never offset from where the
      // signature happens to sit.
      const result = await signaturesApi.finalize(contractId, {
        contract_date: selectedDate,
        apply_paired_dates: true,
      });
      navigate(`/contracts/${contractId}/final`, { state: { fileHash: result.file_hash } });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not generate the final contract');
    } finally {
      setBusy(false);
    }
  };

  const blocked = contract?.review_status !== 'approved' || result?.can_sign === false;
  const pairedDateCount = dateFields.filter(
    (field) => field.paired_signature_field_id && signedFieldIds.has(field.paired_signature_field_id),
  ).length;

  return (
    <div className="review">
      <div className="review__document">
        {error && <p className="alert alert--error">{error}</p>}
        <PdfViewer
          viewer={viewer}
          interactive={!blocked}
          onCanvasClick={(page, _point, suggested) => {
            if (blocked) return;
            setPending({ page, bbox: suggested, fieldId: null });
          }}
        >
          {/* Detected signature slots: clicking one places the signature at the
              template's coordinates rather than wherever the pointer landed. */}
          {pageSignatureFields.map((field) => (
            <button
              key={field.field_id}
              type="button"
              className={`slot${signedFieldIds.has(field.field_id) ? ' slot--filled' : ''}`}
              style={{
                left: field.bbox.x * viewer.scale,
                top: field.bbox.y * viewer.scale,
                width: field.bbox.width * viewer.scale,
                height: field.bbox.height * viewer.scale,
              }}
              onClick={(event) => {
                event.stopPropagation();
                if (blocked || signedFieldIds.has(field.field_id)) return;
                setPending({ page: field.page, bbox: field.bbox, fieldId: field.field_id });
              }}
            >
              <span className="slot__label">
                {signedFieldIds.has(field.field_id) ? 'Signed' : field.label}
              </span>
            </button>
          ))}

          {signatures
            .filter((signature) => signature.page_number === viewer.currentPage)
            .map((signature) => (
              <div
                key={signature.id}
                className="placed-signature"
                style={{
                  left: signature.bbox.x * viewer.scale,
                  top: signature.bbox.y * viewer.scale,
                  width: signature.bbox.width * viewer.scale,
                  height: signature.bbox.height * viewer.scale,
                }}
              />
            ))}
        </PdfViewer>
      </div>

      <div className="review__panel">
        <div className="card">
          <h2>Signatures</h2>
          {blocked && (
            <p className="alert alert--error">
              This contract is not cleared for signing. It must be approved by a reviewer with no
              critical issues outstanding.
            </p>
          )}
          <p className="hint">
            Click a highlighted signature slot on the page, or anywhere on the document to place a
            free-form signature.
          </p>

          <ul className="list">
            {signatures.map((signature) => (
              <li key={signature.id} className="list__item">
                <span>
                  Page {signature.page_number} · {signature.field_id ?? 'free placement'}
                </span>
                <button
                  type="button"
                  className="button button--link"
                  onClick={() => removeSignature(signature.id)}
                >
                  Remove
                </button>
              </li>
            ))}
            {signatures.length === 0 && <li className="list__item">No signatures placed yet.</li>}
          </ul>
        </div>

        <div className="card">
          <h2>Contract date</h2>
          <DatePicker value={selectedDate} onChange={setSelectedDate} />
          <p className="hint">
            {pairedDateCount > 0
              ? `${pairedDateCount} date field${pairedDateCount === 1 ? '' : 's'} paired with your signatures will be filled automatically.`
              : 'Date fields paired with a signature slot are filled automatically when you finalise.'}
          </p>
        </div>

        <div className="card">
          <button
            type="button"
            className="button button--primary button--block"
            disabled={busy || blocked || signatures.length === 0}
            onClick={finalize}
          >
            {busy ? 'Generating…' : 'Generate final contract'}
          </button>
        </div>
      </div>

      {pending && (
        <SignaturePad
          busy={busy}
          onCancel={() => setPending(null)}
          onConfirm={confirmSignature}
          title={pending.fieldId ? `Sign: ${pending.fieldId}` : 'Place a signature'}
        />
      )}
    </div>
  );
}
