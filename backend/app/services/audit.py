"""Append-only audit logging. Every state change on a contract lands here."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.pii import redact_audit_details
from app.models.audit import AuditLog
from app.models.user import User

# Actions recorded across the lifecycle.
TEMPLATE_UPLOADED = "template_uploaded"
TEMPLATE_ANALYZED = "template_analyzed"
TEMPLATE_FIELD_UPDATED = "template_field_updated"
CONTRACT_UPLOADED = "contract_uploaded"
CONTRACT_PARSED = "contract_parsed"
COMPARISON_RUN = "comparison_run"
FIELD_CORRECTED = "field_corrected"
FIELD_REVEALED = "field_revealed"
REVIEW_SUBMITTED = "review_submitted"
SIGNATURE_ADDED = "signature_added"
SIGNATURE_REMOVED = "signature_removed"
DATE_ADDED = "date_added"
CONTRACT_FINALIZED = "contract_finalized"
FINAL_DOWNLOADED = "final_downloaded"


def log(
    db: Session,
    action: str,
    *,
    contract_id: UUID | None = None,
    template_id: UUID | None = None,
    actor: User | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    commit: bool = False,
) -> AuditLog:
    entry = AuditLog(
        action=action,
        contract_id=contract_id,
        template_id=template_id,
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        actor_role=actor.role if actor else None,
        # A field correction carries the old and new value; for a sensitive
        # field those must never land in an append-only table.
        details=redact_audit_details(details or {}),
        ip_address=ip_address,
        user_agent=(user_agent or "")[:500] or None,
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry
