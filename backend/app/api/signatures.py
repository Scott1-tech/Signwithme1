"""Signature capture, placement, and final PDF generation."""
from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import assert_can_view_contract, decode_signature_image, get_contract_or_404
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import client_ip, get_current_user
from app.models.contract import Contract
from app.models.signature import Signature
from app.models.template import Template
from app.models.user import User
from app.schemas.contract import (
    ContractFinalization,
    FinalizeResponse,
    SignatureOut,
    SignaturePlacementIn,
)
from app.services import audit
from app.services.comparison_engine import _index_schema
from app.services.geometry import BBox
from app.services.pdf_builder import DatePlacement, PdfBuilder, SignaturePlacement, sha256_bytes
from app.services.storage import final_key, signature_key, storage
from app.services.validators import format_date, parse_date

router = APIRouter(prefix="/api/contracts", tags=["signatures"])


def _assert_signable(contract: Contract) -> dict:
    """The authoritative signing gate.

    The frontend hides the finalise button when `can_sign` is false, but that is
    a convenience. This check is the control: without it, a client could post
    straight to this endpoint and sign a contract with critical FMCSA
    violations outstanding.
    """
    comparison = contract.comparison_result or {}
    if contract.status in ("uploaded", "parsing"):
        raise ConflictError("Contract has not finished analysis")
    if contract.status == "completed":
        raise ConflictError("Contract is already finalised")
    if not comparison:
        raise ConflictError("Contract has not been compared against its template")
    if contract.review_status != "approved":
        raise ConflictError("Contract must be approved by a reviewer before signing")
    if not comparison.get("can_sign", False):
        raise ConflictError(
            "Contract has unresolved critical issues and cannot be signed: "
            f"{len(comparison.get('missing_required', []))} missing required field(s), "
            f"{len(comparison.get('inconsistencies', []))} inconsistency(ies), "
            f"{len(comparison.get('fmcsa_violations', []))} FMCSA violation(s)"
        )
    return comparison


@router.post("/{contract_id}/signatures", response_model=SignatureOut, status_code=201)
def place_signature(
    contract_id: UUID,
    placement: SignaturePlacementIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Store a captured signature image and its placement.

    The canvas produces base64; it is uploaded to object storage here so the
    signature row can hold a path and a hash, as the audit trail requires.
    """
    contract = get_contract_or_404(db, contract_id)
    assert_can_view_contract(contract, user)
    _assert_signable(contract)

    image_bytes = decode_signature_image(placement.image_data)
    signature = Signature(
        id=uuid4(),
        contract_id=contract.id,
        signer_name=placement.signer_name or user.full_name,
        signer_email=str(placement.signer_email) if placement.signer_email else user.email,
        signer_role=placement.signer_role,
        signature_image_path="",
        signature_hash=sha256_bytes(image_bytes),
        page_number=placement.page,
        bbox=placement.bbox.model_dump(),
        field_id=placement.field_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    key = signature_key(contract.id, signature.id)
    storage.put_bytes(key, image_bytes, content_type="image/png")
    signature.signature_image_path = key

    db.add(signature)
    audit.log(
        db,
        audit.SIGNATURE_ADDED,
        contract_id=contract.id,
        actor=user,
        details={
            "signature_id": str(signature.id),
            "field_id": placement.field_id,
            "page": placement.page,
            "signature_hash": signature.signature_hash,
        },
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(signature)
    return signature


@router.get("/{contract_id}/signatures", response_model=list[SignatureOut])
def list_signatures(
    contract_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contract = get_contract_or_404(db, contract_id)
    assert_can_view_contract(contract, user)
    return list(
        db.scalars(select(Signature).where(Signature.contract_id == contract.id).order_by(Signature.signed_at))
    )


@router.delete("/{contract_id}/signatures/{signature_id}")
def remove_signature(
    contract_id: UUID,
    signature_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contract = get_contract_or_404(db, contract_id)
    assert_can_view_contract(contract, user)
    if contract.status == "completed":
        raise ConflictError("Cannot remove a signature from a finalised contract")

    signature = db.get(Signature, signature_id)
    if signature is None or signature.contract_id != contract.id:
        raise NotFoundError("Signature not found on this contract")

    storage.delete(signature.signature_image_path)
    db.delete(signature)
    audit.log(
        db,
        audit.SIGNATURE_REMOVED,
        contract_id=contract.id,
        actor=user,
        details={"signature_id": str(signature_id)},
        ip_address=client_ip(request),
    )
    db.commit()
    return {"signature_id": str(signature_id), "removed": True}


@router.post("/{contract_id}/finalize", response_model=FinalizeResponse)
def finalize_contract(
    contract_id: UUID,
    finalization: ContractFinalization,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate the final signed PDF with all signatures and dates overlaid."""
    contract = get_contract_or_404(db, contract_id)
    assert_can_view_contract(contract, user)
    _assert_signable(contract)

    template = db.get(Template, contract.template_id)
    if template is None:
        raise NotFoundError("Template for this contract no longer exists")
    index = _index_schema(template.field_schema)

    signatures = list(
        db.scalars(select(Signature).where(Signature.contract_id == contract.id))
    )
    if not signatures:
        raise ConflictError("No signatures have been placed on this contract")

    signature_placements = [
        SignaturePlacement(
            page=row.page_number,
            bbox=BBox.from_dict(row.bbox),
            image_bytes=storage.get_bytes(row.signature_image_path),
            field_id=row.field_id,
        )
        for row in signatures
    ]

    date_placements = _resolve_dates(finalization, signatures, index)

    source = storage.get_bytes(contract.file_path)
    result = PdfBuilder().build_final_contract(
        source,
        signature_placements,
        date_placements,
        title=f"Signed Contract - {contract.contractor_name or contract.id}",
    )

    key = final_key(contract.id)
    storage.put_bytes(key, result.pdf_bytes)
    contract.final_file_path = key
    contract.final_file_hash = result.sha256
    contract.status = "completed"

    for placement in date_placements:
        audit.log(
            db,
            audit.DATE_ADDED,
            contract_id=contract.id,
            actor=user,
            details={"field_id": placement.field_id, "page": placement.page, "value": placement.value},
        )
    audit.log(
        db,
        audit.CONTRACT_FINALIZED,
        contract_id=contract.id,
        actor=user,
        details={
            "signatures": len(signature_placements),
            "dates": len(date_placements),
            # Recorded so any later copy can be checked against the original.
            "final_file_hash": result.sha256,
            "page_count": result.page_count,
        },
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()

    return FinalizeResponse(
        contract_id=contract.id,
        status="completed",
        file_hash=result.sha256,
        download_url=f"/api/download/{contract.id}/final",
    )


def _resolve_dates(
    finalization: ContractFinalization,
    signatures: list[Signature],
    index: dict[str, dict],
) -> list[DatePlacement]:
    """Turn the requested contract date into placements at the template's own
    date-field coordinates."""
    placements: list[DatePlacement] = []
    seen: set[str] = set()

    for explicit in finalization.dates or []:
        bbox_source = explicit.bbox.model_dump() if explicit.bbox else None
        if bbox_source is None:
            field = index.get(explicit.field_id or "")
            if field is None:
                raise ValidationError(
                    f"Date placement needs either a bbox or a known field_id (got {explicit.field_id!r})"
                )
            bbox_source = field["bbox"]
        placements.append(
            DatePlacement(
                page=explicit.page,
                bbox=BBox.from_dict(bbox_source),
                value=_render_date(explicit.value),
                field_id=explicit.field_id,
            )
        )
        if explicit.field_id:
            seen.add(explicit.field_id)

    if finalization.apply_paired_dates and finalization.contract_date:
        rendered = _render_date(finalization.contract_date)
        for signature in signatures:
            field = index.get(signature.field_id or "")
            paired_id = (field or {}).get("paired_date_field_id")
            if not paired_id or paired_id in seen:
                continue
            paired = index.get(paired_id)
            if paired is None:
                continue
            placements.append(
                DatePlacement(
                    page=int(paired.get("page") or signature.page_number),
                    bbox=BBox.from_dict(paired["bbox"]),
                    value=rendered,
                    field_id=paired_id,
                )
            )
            seen.add(paired_id)

    return placements


def _render_date(value: str) -> str:
    """Contracts print MM/DD/YYYY; the date input submits ISO."""
    parsed = parse_date(value)
    if parsed is None:
        raise ValidationError(f"Could not parse date: {value!r}")
    if parsed > date(2100, 1, 1):
        raise ValidationError("Date is implausibly far in the future")
    return format_date(parsed)
