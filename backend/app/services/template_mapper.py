"""Bridge between a template's field schema and a contract's per-field rows.

`contract_fields` is authoritative; `contracts.extracted_data` is a read cache
rebuilt from those rows so the review UI can load one document in a single
query.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import pii
from app.models.field import ContractField
from app.services import validators as v
from app.services.comparison_engine import _index_schema


def schema_fields(template_schema: dict) -> dict[str, dict]:
    return _index_schema(template_schema)


def normalized_for(field_type: str, field_id: str, value) -> str | None:
    """Store a comparison-ready form alongside the raw extraction."""
    if v.is_blank(value):
        return None
    if field_type == "date" or "date" in field_id or "exp" in field_id or "dob" in field_id:
        parsed = v.parse_date(value)
        return parsed.isoformat() if parsed else None
    if "cdl" in field_id or "ein" in field_id or "ssn" in field_id or "unit" in field_id:
        return v.normalize_identifier(value)
    if "name" in field_id:
        return v.normalize_name(value)
    return v.normalize_text(value)


def sync_contract_fields(
    db: Session,
    contract_id: UUID,
    template_schema: dict,
    extracted: dict[str, dict],
    comparison: dict | None = None,
) -> list[ContractField]:
    """Upsert one row per template field. Safe to re-run: the unique constraint
    on (contract_id, template_field_id) means re-parsing updates rather than
    duplicates."""
    index = schema_fields(template_schema)
    existing = {
        row.template_field_id: row
        for row in db.scalars(
            select(ContractField).where(ContractField.contract_id == contract_id)
        )
    }

    invalid_by_field: dict[str, str] = {}
    for bucket in ("inconsistencies", "warnings"):
        for issue in (comparison or {}).get(bucket, []) or []:
            if issue.get("field_id"):
                invalid_by_field[issue["field_id"]] = issue.get("issue", "Invalid value")

    rows: list[ContractField] = []
    for field_id, field in index.items():
        data = extracted.get(field_id) or {}
        field_type = field.get("field_type", "text_line")
        raw_value = data.get("value")
        filled = _is_filled(data, field_type)

        error = invalid_by_field.get(field_id)
        if error:
            status = "invalid"
        elif filled:
            status = "filled"
        else:
            status = "empty"

        row = existing.get(field_id)
        if row is None:
            row = ContractField(contract_id=contract_id, template_field_id=field_id)
            db.add(row)

        row.field_type = field_type
        row.status = status
        normalized = normalized_for(field_type, field_id, raw_value)
        stored_raw = None if raw_value is None else str(raw_value)
        if pii.is_sensitive(field_id):
            # SSNs, EINs and dates of birth are encrypted before they touch the
            # database; only an explicit admin reveal decrypts them again.
            stored_raw = pii.encrypt(stored_raw)
            normalized = pii.encrypt(normalized)
        row.raw_value = stored_raw
        row.normalized_value = normalized
        row.confidence_score = data.get("confidence")
        row.is_required = bool(field.get("required", False))
        row.is_valid = None if not filled else error is None
        row.validation_error = error
        row.bbox = field.get("bbox")
        row.page_number = field.get("page")
        row.extra = {
            key: data[key]
            for key in ("selected", "checked", "has_signature", "rows", "extra")
            if key in data
        }
        rows.append(row)

    db.flush()
    return rows


def extracted_cache(rows: list[ContractField]) -> dict[str, dict]:
    """Rebuild contracts.extracted_data from the authoritative field rows."""
    cache: dict[str, dict] = {}
    for row in rows:
        sensitive = pii.is_sensitive(row.template_field_id)
        # The cache is a display artefact and is read back by the comparison
        # re-run, so it holds a masked value -- never the plaintext, never the
        # ciphertext.
        display = (
            pii.mask(pii.decrypt(row.raw_value), row.template_field_id)
            if sensitive
            else row.raw_value
        )
        entry: dict = {
            "value": display,
            "normalized": None if sensitive else row.normalized_value,
            "sensitive": sensitive,
            "redacted": sensitive,
            "confidence": float(row.confidence_score) if row.confidence_score is not None else 0.0,
            "detected": row.status in ("filled", "verified"),
            "status": row.status,
        }
        entry.update(row.extra or {})
        cache[row.template_field_id] = entry
    return cache


def _is_filled(data: dict, field_type: str) -> bool:
    if field_type == "checkbox_group":
        return bool(data.get("selected"))
    if field_type == "checkbox":
        return bool(data.get("checked"))
    if field_type == "signature":
        return bool(data.get("has_signature"))
    if field_type == "table":
        return any(any(cell for cell in row) for row in data.get("rows", []))
    return not v.is_blank(data.get("value"))
