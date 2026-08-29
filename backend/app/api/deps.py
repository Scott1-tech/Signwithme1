"""Shared route dependencies: upload validation and record loaders."""
from __future__ import annotations

import base64
import binascii
import re
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import NotFoundError, PermissionError_, ValidationError
from app.core.security import ROLE_ADMIN, ROLE_REVIEWER
from app.models.contract import Contract
from app.models.template import Template
from app.models.user import User

PDF_MAGIC = b"%PDF-"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
DATA_URL_RE = re.compile(r"^data:image/(png|jpeg);base64,", re.IGNORECASE)


async def read_pdf_upload(file: UploadFile) -> bytes:
    """Read an upload, enforcing type, size and actual PDF content.

    Trusting the declared content type alone would let any file through.
    """
    if file.content_type not in (None, "application/pdf", "application/octet-stream"):
        raise ValidationError(f"Expected a PDF, got content type {file.content_type}")

    data = await file.read()
    if not data:
        raise ValidationError("Uploaded file is empty")
    if len(data) > settings.max_upload_bytes:
        raise ValidationError(
            f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)}MB limit"
        )
    if not data.startswith(PDF_MAGIC):
        raise ValidationError("File is not a valid PDF")
    return data


def decode_signature_image(image_data: str) -> bytes:
    """Accept a PNG data URL from the canvas pad, or bare base64."""
    payload = DATA_URL_RE.sub("", image_data.strip())
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("Signature image is not valid base64") from exc
    if not data:
        raise ValidationError("Signature image is empty")
    if len(data) > 5 * 1024 * 1024:
        raise ValidationError("Signature image is too large")
    if not data.startswith(PNG_MAGIC) and not data.startswith(b"\xff\xd8\xff"):
        raise ValidationError("Signature image must be a PNG or JPEG")
    return data


def get_template_or_404(db: Session, template_id: UUID) -> Template:
    template = db.get(Template, template_id)
    if template is None:
        raise NotFoundError(f"Template {template_id} not found")
    return template


def get_contract_or_404(db: Session, contract_id: UUID) -> Contract:
    contract = db.get(Contract, contract_id)
    if contract is None:
        raise NotFoundError(f"Contract {contract_id} not found")
    return contract


def assert_can_view_contract(contract: Contract, user: User) -> None:
    """Contractors see only their own contracts; reviewers and admins see all."""
    if user.role in (ROLE_ADMIN, ROLE_REVIEWER):
        return
    if contract.uploaded_by == user.id:
        return
    if contract.contractor_email and contract.contractor_email.lower() == user.email.lower():
        return
    raise PermissionError_("You do not have access to this contract")
