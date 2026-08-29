from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import BBoxModel


class ContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    template_id: UUID
    contractor_name: str | None
    contractor_email: str | None
    status: str
    review_status: str
    error_message: str | None
    reviewed_at: datetime | None
    review_notes: str | None
    created_at: datetime
    updated_at: datetime


class ContractDetailOut(ContractOut):
    extracted_data: dict
    comparison_result: dict
    final_available: bool = False


class ContractCreateResponse(BaseModel):
    contract_id: UUID
    task_id: str | None
    status: str


class ContractFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    template_field_id: str
    field_type: str
    status: str
    raw_value: str | None
    normalized_value: str | None
    confidence_score: float | None
    is_required: bool
    is_valid: bool | None
    validation_error: str | None
    bbox: BBoxModel | None
    page_number: int | None
    extra: dict = {}


class FieldCorrection(BaseModel):
    """A reviewer overriding what the parser read."""

    value: str | None = None
    selected: list[str] | None = None
    checked: bool | None = None
    mark_verified: bool = True


class ReviewSubmission(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    notes: str | None = None


class SignaturePlacementIn(BaseModel):
    page: int = Field(ge=1)
    bbox: BBoxModel
    field_id: str | None = None
    signer_name: str | None = None
    signer_email: EmailStr | None = None
    signer_role: str = Field(default="contractor", pattern="^(contractor|company_rep)$")
    # PNG data URL or bare base64 produced by the canvas signature pad.
    image_data: str


class SignatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contract_id: UUID
    signer_name: str | None
    signer_email: str | None
    signer_role: str
    page_number: int
    bbox: BBoxModel
    field_id: str | None
    signed_at: datetime


class DatePlacementIn(BaseModel):
    page: int = Field(ge=1)
    bbox: BBoxModel | None = None
    field_id: str | None = None
    value: str


class ContractFinalization(BaseModel):
    """Dates default to every date field paired with a placed signature, using
    the template's own coordinates rather than an offset from the signature."""

    contract_date: str | None = None
    dates: list[DatePlacementIn] | None = None
    apply_paired_dates: bool = True


class FinalizeResponse(BaseModel):
    contract_id: UUID
    status: str
    file_hash: str
    download_url: str
