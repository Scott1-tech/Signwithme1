"""Template upload, field-schema retrieval, and manual field correction."""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_template_or_404, read_pdf_upload
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import ROLE_ADMIN, ROLE_REVIEWER, client_ip, get_current_user, require_role
from app.models.template import Template
from app.models.user import User
from app.schemas.template import (
    FieldUpdate,
    TemplateCreateResponse,
    TemplateDetailOut,
    TemplateOut,
)
from app.services import audit
from app.services.pdf_parser import sha256_bytes
from app.services.storage import storage, template_key
from app.workers.tasks import analyze_template_task

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.post("", response_model=TemplateCreateResponse, status_code=202)
async def upload_template(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form("Untitled Template"),
    description: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(ROLE_ADMIN)),
):
    """Upload a blank contract template. Field detection runs in the background.

    The template row is created up front so the client has an id to poll,
    rather than only an opaque task id.
    """
    data = await read_pdf_upload(file)

    template = Template(
        id=uuid4(),
        name=name,
        description=description,
        file_hash=sha256_bytes(data),
        status="processing",
        created_by=user.id,
    )
    key = template_key(template.id)
    storage.ensure_bucket()
    storage.put_bytes(key, data)
    template.file_path = key

    db.add(template)
    audit.log(
        db,
        audit.TEMPLATE_UPLOADED,
        template_id=template.id,
        actor=user,
        details={"name": name, "bytes": len(data)},
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()

    task = analyze_template_task.delay(str(template.id))
    return TemplateCreateResponse(template_id=template.id, task_id=task.id, status="processing")


@router.get("", response_model=list[TemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    include_archived: bool = False,
):
    query = select(Template).order_by(Template.created_at.desc())
    if not include_archived:
        query = query.where(Template.status != "archived")
    return list(db.scalars(query))


@router.get("/{template_id}", response_model=TemplateDetailOut)
def get_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return get_template_or_404(db, template_id)


@router.get("/{template_id}/fields")
def get_template_fields(
    template_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The detected field structure, for review and correction by an admin."""
    template = get_template_or_404(db, template_id)
    return template.field_schema


@router.get("/{template_id}/file")
def get_template_file(
    template_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stream the template PDF.

    Served through the API rather than by a link into the storage layer: the
    same authorisation check then covers every read, and there is no storage
    endpoint that has to be reachable from a browser.
    """
    template = get_template_or_404(db, template_id)
    if not template.file_path:
        raise NotFoundError("Template file is not available")
    return StreamingResponse(
        storage.stream(template.file_path),
        media_type="application/pdf",
        headers={"Cache-Control": "no-store"},
    )


@router.put("/{template_id}/fields/{field_id}")
def update_field(
    template_id: UUID,
    field_id: str,
    updates: FieldUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(ROLE_ADMIN, ROLE_REVIEWER)),
):
    """Adjust a detected field's position or properties.

    Auto-detection is good but not perfect; a reviewer nudging a signature box
    is the difference between a signature landing on the line or beside it.
    """
    template = get_template_or_404(db, template_id)
    schema = dict(template.field_schema or {})
    pages = [dict(page) for page in schema.get("pages", [])]

    patch = updates.model_dump(exclude_unset=True)
    if "bbox" in patch and patch["bbox"] is not None:
        patch["bbox"] = dict(patch["bbox"])
    if "options" in patch and patch["options"] is not None:
        patch["options"] = [dict(option) for option in patch["options"]]

    found = False
    for page in pages:
        fields = []
        for field in page.get("fields", []):
            if field.get("field_id") == field_id:
                field = {**field, **patch}
                found = True
            fields.append(field)
        page["fields"] = fields
    if not found:
        raise NotFoundError(f"Field {field_id} not found in template {template_id}")

    schema["pages"] = pages
    template.field_schema = schema
    audit.log(
        db,
        audit.TEMPLATE_FIELD_UPDATED,
        template_id=template.id,
        actor=user,
        details={"field_id": field_id, "changes": list(patch.keys())},
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return {"field_id": field_id, "updated": list(patch.keys())}


@router.post("/{template_id}/reanalyze", response_model=TemplateCreateResponse, status_code=202)
def reanalyze_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(ROLE_ADMIN)),
):
    """Re-run detection. Any manual field corrections are discarded."""
    template = get_template_or_404(db, template_id)
    if not template.file_path:
        raise ConflictError("Template has no stored file to analyse")
    template.status = "processing"
    db.commit()
    task = analyze_template_task.delay(str(template.id))
    return TemplateCreateResponse(template_id=template.id, task_id=task.id, status="processing")


@router.delete("/{template_id}")
def archive_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(ROLE_ADMIN)),
):
    """Archive rather than delete: signed contracts reference their template."""
    template = get_template_or_404(db, template_id)
    template.status = "archived"
    db.commit()
    return {"template_id": str(template_id), "status": "archived"}
