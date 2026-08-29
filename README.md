# Contract Signing App

Template-driven contract review, comparison and signing for FMCSA-regulated
carriers. Upload a blank contract template once; the system detects every
fillable region and stores it as a field schema. Uploaded contracts are then
parsed against that schema, compared for missing fields, cross-page
inconsistencies and FMCSA compliance, reviewed in a side-by-side UI, signed on
canvas, and rendered into a final PDF with a full audit trail.

## Stack

| Layer | Technology |
| --- | --- |
| Frontend | React 18, TypeScript, Vite, pdf.js |
| Backend | FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2 |
| Workers | Celery + Redis |
| Data | PostgreSQL 15 (JSONB field schemas), MinIO / S3 |

## Running it

```bash
cp .env.example .env      # then edit the passwords and JWT secret
docker compose up --build
```

* Frontend — http://localhost:3000
* API docs — http://localhost:8000/docs
* MinIO console — http://localhost:9001

Migrations run automatically before the API starts. If `SEED_ADMIN_EMAIL` and
`SEED_ADMIN_PASSWORD` are set, an admin account is created on first boot —
self-registration only ever produces contractors.

### Local development without Docker

```bash
cd backend
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
celery -A app.workers.celery_app worker --loglevel=info   # in a second shell

cd ../frontend
npm install
npm run dev
```

### Tests

```bash
cd backend && python -m pytest -q      # 47 tests
cd frontend && npm run typecheck
```

## The flow

1. **Template upload** (admin) — the PDF is stored, and `analyze_template_task`
   detects text fields, checkboxes, signature regions and tables, writing a
   `field_schema` with real coordinates for every one.
2. **Contract upload** — `process_contract_task` crops each region of the
   uploaded PDF, reads what the contractor wrote, and runs the comparison.
3. **Review** — the PDF renders with missing fields highlighted in place;
   the sidebar lists missing fields, cross-page inconsistencies, FMCSA
   violations and format warnings.
4. **Signing** — a reviewer approves, signatures are drawn on canvas and placed
   at the template's own signature coordinates.
5. **Finalise** — signatures and dates are overlaid onto the original PDF, the
   result is hashed, and every step is in the audit log.

## Design notes

These are the decisions that are easy to get wrong, and how this codebase
handles them.

### One coordinate convention

Three conventions are in play: pdfplumber (points, top-left origin,
`x0/top/x1/bottom`), reportlab (points, **bottom-left** origin), and the browser
(CSS pixels, top-left, scaled by zoom). Everything crossing an API or database
boundary uses one canonical form — points, top-left origin,
`{x, y, width, height}` — and conversion happens at exactly two edges:
`BBox.to_reportlab()` when drawing overlays, and multiplying by the viewer's
`scale` when rendering highlights. Mixing these up mirrors signatures
vertically or drifts every highlight the moment someone zooms.

### Field detection produces real coordinates

Bounding boxes come from `page.extract_words()` positions, not placeholders: the
detector maps each regex match back to the words it covers and extends the fill
region across the underscore run that follows. Highlighting and signature
placement both depend on this being accurate.

Repeated labels get an occurrence suffix (`p1_date`, `p1_date_2`), so the
contractor's date and the company representative's date on the same page stay
distinct instead of deduplicating into one. Checkboxes are detected both as
`☐` glyphs and as small vector squares — base-14 fonts have no U+2610 glyph, so
many real templates draw rectangles instead, and a missed checkbox is a missed
required field.

### Normalisation before comparison

Cross-field checks compare normalised values. `Oh Rt305248` and `OH-RT305248`
are the same licence; comparing raw strings would raise a *critical* CDL
mismatch on OCR casing noise and block signing. Names tolerate an added or
omitted middle name and `LAST, FIRST` ordering; dates parse `01/30/2030`,
`01.30.2030` and `1/30/2030` to the same day.

### Missing data fails compliance

`if value and value != "yes"` silently approves a blank DOT-eligibility box. An
absent compliance answer is treated as a violation, not a pass. Rules whose
fields the template does not contain are skipped rather than failed.

### The signing gate is server-side

`ComparisonEngine.can_sign` is enforced in `_assert_signable()` before any
signature is stored and again before the final PDF is built, alongside reviewer
approval. The frontend's hidden button is a convenience; a client posting
directly to the endpoint still cannot sign a contract with outstanding critical
issues.

### Dates use their own coordinates

Signature fields carry a `paired_date_field_id`, resolved at detection time from
proximity on the page. Finalisation writes the contract date into that field's
own bounding box rather than offsetting a fixed number of points from the
signature, and renders `MM/DD/YYYY` — the format the contract prints — rather
than the ISO value the date input submits.

### Integrity and access

Every artefact (template, upload, signature image, final PDF) lives in object
storage, hashed with SHA-256. `GET /api/download/{id}/verify` re-hashes the
stored document and compares it with what was recorded at signing. Downloads
require an authenticated, authorised caller; the underlying object is reached
through a short-lived presigned URL, never a stable public path — these
documents contain SSNs and licence numbers.

## Schema notes

* `contract_fields` is authoritative; `contracts.extracted_data` is a read cache
  rebuilt from those rows.
* `UNIQUE (contract_id, template_field_id)` — without it, re-parsing a contract
  duplicates every field row instead of updating it.
* `ON DELETE RESTRICT` on `contracts.template_id`: a signed contract must never
  lose the template it was judged against. `CASCADE` on fields and signatures.
* `audit_logs.actor_id` is deliberately **not** a foreign key, so log rows
  survive user deletion.
* `updated_at` is maintained by an ORM hook and by a database trigger, so direct
  SQL writes stay honest.

## Not yet built

* **`ai-service`** — the optional ML field detector for scanned PDFs from the
  original architecture. Not implemented, and deliberately absent from
  `docker-compose.yml` rather than declared as a service that would fail to
  build. The current parser handles digital PDFs; scanned documents need OCR
  (pytesseract) wired into `PdfParser`.
* **Cryptographic PDF signing.** Signatures are drawn images overlaid on the
  document, with SHA-256 hashes and a full audit trail for evidentiary value.
  PKI-backed digital signatures (PAdES) are a separate piece of work.

## Layout

```
backend/
  app/
    api/         templates, contracts, review, signatures, dates, download, auth
    core/        config, database, security (JWT + roles), exceptions
    models/      SQLAlchemy ORM
    schemas/     Pydantic request/response models
    services/    geometry, field_detector, pdf_parser, comparison_engine,
                 validators, pdf_builder, template_mapper, storage, audit
    workers/     Celery app and tasks
  alembic/       migrations
  tests/         47 tests, no database required
frontend/
  src/
    api/         typed client (auth, templates, contracts, signatures)
    components/  PdfViewer, FieldHighlighter, SignaturePad, ComparisonSidebar, …
    hooks/       usePdfViewer, useComparison, useSignature, useAuth
    pages/       Dashboard, TemplateManager, ContractUpload, ReviewPage,
                 SignaturePage, FinalContract, ReviewQueue, Login
    types/       field, template, contract, comparison
```
