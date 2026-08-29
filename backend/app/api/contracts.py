"""Contract upload, comparison results, and per-field inspection."""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    assert_can_view_contract,
    get_contract_or_404,
    get_template_or_404,
    read_pdf_upload,
)
from app.core import pii
from app.core.database import get_db
from app.core.exceptions import ConflictError
from app.core.security import (
    ROLE_ADMIN,
    ROLE_REVIEWER,
    client_ip,
    get_current_user,
    require_role,
)
from app.models.contract import Contract
from app.models.field import ContractField
from app.models.user import User
from app.schemas.comparison import ComparisonOut
from app.schemas.contract import (
    ContractCreateResponse,
    ContractDetailOut,
    ContractFieldOut,
    ContractOut,
    FieldCorrection,
)
from app.services import audit
from app.services.comparison_engine import ComparisonEngine
from app.services.pdf_parser import sha256_bytes
from app.services.storage import contract_key, storage
from app.services.template_mapper import extracted_cache, normalized_for
from app.workers.tasks import process_contract_task

router = APIRouter(prefix="/api/contracts", tags=["contracts"])


def _field_out(row: ContractField) -> ContractFieldOut:
    """Serialise a field row with sensitive values masked.

    Stored sensitive values are ciphertext, so returning them raw would be
    useless as well as unsafe; the plaintext is available only through the
    audited reveal endpoint below.
    """
    out = ContractFieldOut.model_validate(row)
    if pii.is_sensitive(row.template_field_id):
        out.raw_value = pii.mask(pii.decrypt(row.raw_value), row.template_field_id)
        out.normalized_value = None
    return out


@router.post("", response_model=ContractCreateResponse, status_code=202)
async def upload_contract(
    request: Request,
    template_id: UUID = Form(...),
    file: UploadFile = File(...),
    contractor_name: str | None = Form(None),
    contractor_email: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Upload a filled contract. Parsing and comparison run in the background."""
    template = get_template_or_404(db, template_id)
    if template.status != "ready":
        raise ConflictError(
            f"Template is '{template.status}'; it must finish analysis before contracts are uploaded"
        )

    data = await read_pdf_upload(file)
    contract = Contract(
        id=uuid4(),
        template_id=template.id,
        contractor_name=contractor_name,
        contractor_email=contractor_email,
        file_hash=sha256_bytes(data),
        file_path="",
        status="uploaded",
        uploaded_by=user.id,
    )
    key = contract_key(contract.id)
    storage.ensure_bucket()
    storage.put_bytes(key, data)
    contract.file_path = key

    db.add(contract)
    audit.log(
        db,
        audit.CONTRACT_UPLOADED,
        contract_id=contract.id,
        template_id=template.id,
        actor=user,
        details={"bytes": len(data), "file_hash": contract.file_hash},
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()

    task = process_contract_task.delay(str(contract.id))
    return ContractCreateResponse(contract_id=contract.id, task_id=task.id, status="uploaded")


@router.get("", response_model=list[ContractOut])
def list_contracts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    status: str | None = None,
    template_id: UUID | None = None,
):
    query = select(Contract).order_by(Contract.created_at.desc())
    if status:
        query = query.where(Contract.status == status)
    if template_id:
        query = query.where(Contract.template_id == template_id)
    if user.role not in (ROLE_ADMIN, ROLE_REVIEWER):
        query = query.where(Contract.uploaded_by == user.id)
    return list(db.scalars(query))


@router.get("/{contract_id}", response_model=ContractDetailOut)
def get_contract(
    contract_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    contract = get_contract_or_404(db, contract_id)
    assert_can_view_contract(contract, user)
    detail = ContractDetailOut.model_validate(contract)
    detail.final_available = bool(contract.final_file_path)
    return detail


@router.get("/{contract_id}/compare", response_model=ComparisonOut)
def get_comparison(
    contract_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """What is missing, inconsistent or non-compliant."""
    contract = get_contract_or_404(db, contract_id)
    assert_can_view_contract(contract, user)
    if not contract.comparison_result:
        raise ConflictError(f"Contract is '{contract.status}'; comparison is not ready yet")
    return contract.comparison_result


@router.post("/{contract_id}/compare", response_model=ComparisonOut)
def rerun_comparison(
    contract_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Re-evaluate the rules against the current field values, without
    re-parsing the PDF. Used after a reviewer corrects a misread field."""
    contract = get_contract_or_404(db, contract_id)
    assert_can_view_contract(contract, user)
    template = get_template_or_404(db, contract.template_id)

    result = ComparisonEngine().compare(
        contract.extracted_data, template.field_schema, contract_id=str(contract.id)
    ).to_dict()
    contract.comparison_result = result
    audit.log(
        db,
        audit.COMPARISON_RUN,
        contract_id=contract.id,
        actor=user,
        details={"trigger": "manual", "can_sign": result["can_sign"]},
    )
    db.commit()
    return result


@router.get("/{contract_id}/fields", response_model=list[ContractFieldOut])
def list_contract_fields(
    contract_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int | None = None,
):
    contract = get_contract_or_404(db, contract_id)
    assert_can_view_contract(contract, user)
    query = select(ContractField).where(ContractField.contract_id == contract.id)
    if page is not None:
        query = query.where(ContractField.page_number == page)
    return [_field_out(row) for row in db.scalars(query.order_by(ContractField.page_number))]


@router.patch("/{contract_id}/fields/{field_id}", response_model=ContractFieldOut)
def correct_field(
    contract_id: UUID,
    field_id: str,
    correction: FieldCorrection,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """A reviewer overriding what the parser read from the page."""
    contract = get_contract_or_404(db, contract_id)
    assert_can_view_contract(contract, user)

    row = db.scalar(
        select(ContractField).where(
            ContractField.contract_id == contract.id,
            ContractField.template_field_id == field_id,
        )
    )
    if row is None:
        raise ConflictError(f"Field {field_id} does not exist on this contract")

    sensitive = pii.is_sensitive(field_id)
    previous = pii.decrypt(row.raw_value) if sensitive else row.raw_value
    patch = correction.model_dump(exclude_unset=True)
    if "value" in patch:
        normalized = normalized_for(row.field_type, field_id, patch["value"])
        row.raw_value = pii.encrypt(patch["value"]) if sensitive else patch["value"]
        row.normalized_value = pii.encrypt(normalized) if sensitive else normalized
    if "selected" in patch and patch["selected"] is not None:
        row.extra = {**(row.extra or {}), "selected": patch["selected"]}
    if "checked" in patch and patch["checked"] is not None:
        row.extra = {**(row.extra or {}), "checked": patch["checked"]}

    row.confidence_score = 1.0
    row.validation_error = None
    row.is_valid = True
    row.status = "verified" if correction.mark_verified else "filled"

    db.flush()
    rows = list(db.scalars(select(ContractField).where(ContractField.contract_id == contract.id)))
    contract.extracted_data = extracted_cache(rows)

    audit.log(
        db,
        audit.FIELD_CORRECTED,
        contract_id=contract.id,
        actor=user,
        # audit.log scrubs these for a sensitive field before they are written.
        details={
            "field_id": field_id,
            "from": previous,
            "to": patch.get("value", previous),
        },
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(row)
    return _field_out(row)


@router.get("/{contract_id}/fields/{field_id}/reveal")
def reveal_field(
    contract_id: UUID,
    field_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(ROLE_ADMIN)),
):
    """Decrypt one sensitive value. Admin only, and always audited.

    Reading an SSN is a deliberate act with a record attached, rather than a
    side effect of opening the contract.
    """
    contract = get_contract_or_404(db, contract_id)
    row = db.scalar(
        select(ContractField).where(
            ContractField.contract_id == contract.id,
            ContractField.template_field_id == field_id,
        )
    )
    if row is None:
        raise ConflictError(f"Field {field_id} does not exist on this contract")

    audit.log(
        db,
        audit.FIELD_REVEALED,
        contract_id=contract.id,
        actor=user,
        details={"field_id": field_id},
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        commit=True,
    )
    return {
        "field_id": field_id,
        "value": pii.decrypt(row.raw_value),
        "sensitive": pii.is_sensitive(field_id),
    }


@router.get("/{contract_id}/file")
def get_contract_file(
    contract_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Short-lived presigned URL for the original upload. These documents carry
    SSNs, so the URL expires rather than being a stable public path."""
    contract = get_contract_or_404(db, contract_id)
    assert_can_view_contract(contract, user)
    return {"url": storage.presigned_url(contract.file_path, filename="contract.pdf")}
