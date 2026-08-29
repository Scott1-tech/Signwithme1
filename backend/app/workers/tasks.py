"""Background PDF work. Parsing a 40-page template is far too slow for a request."""
from __future__ import annotations

import logging
from uuid import UUID

from app.core.database import SessionLocal
from app.services import audit
from app.services.comparison_engine import ComparisonEngine
from app.services.field_detector import FieldDetector
from app.services.pdf_parser import PdfParser
from app.services.storage import storage
from app.services.template_mapper import extracted_cache, sync_contract_fields
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="templates.analyze", bind=True, max_retries=2)
def analyze_template_task(self, template_id: str) -> dict:
    """Detect every fillable region in a template and store the field schema."""
    from app.models.template import Template

    db = SessionLocal()
    try:
        template = db.get(Template, UUID(template_id))
        if template is None:
            logger.error("Template %s vanished before analysis", template_id)
            return {"status": "missing"}

        template.status = "processing"
        db.commit()

        with storage.local_copy(template.file_path) as path:
            schema = FieldDetector().build_schema(path)

        template.field_schema = schema
        template.page_count = len(schema.get("pages", []))
        template.status = "ready"
        template.error_message = None
        audit.log(
            db,
            audit.TEMPLATE_ANALYZED,
            template_id=template.id,
            details={"field_count": schema.get("field_count", 0), "pages": template.page_count},
        )
        db.commit()
        return {"status": "ready", "field_count": schema.get("field_count", 0)}
    except Exception as exc:  # noqa: BLE001 - surface the failure on the record
        logger.exception("Template analysis failed for %s", template_id)
        db.rollback()
        template = db.get(Template, UUID(template_id))
        if template is not None:
            template.status = "failed"
            template.error_message = str(exc)[:1000]
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(name="contracts.process", bind=True, max_retries=2)
def process_contract_task(self, contract_id: str) -> dict:
    """Extract every field from an uploaded contract, then compare it against
    its template."""
    from app.models.contract import Contract
    from app.models.template import Template

    db = SessionLocal()
    try:
        contract = db.get(Contract, UUID(contract_id))
        if contract is None:
            return {"status": "missing"}
        template = db.get(Template, contract.template_id)
        if template is None or template.status != "ready":
            contract.status = "failed"
            contract.error_message = "Template is not ready for comparison"
            db.commit()
            return {"status": "failed"}

        contract.status = "parsing"
        db.commit()

        with storage.local_copy(contract.file_path) as path:
            extracted = PdfParser().extract(path, template.field_schema)

        comparison = ComparisonEngine().compare(
            extracted, template.field_schema, contract_id=str(contract.id)
        ).to_dict()

        rows = sync_contract_fields(db, contract.id, template.field_schema, extracted, comparison)
        contract.extracted_data = extracted_cache(rows)
        contract.comparison_result = comparison
        contract.status = "analyzed"
        contract.error_message = None

        audit.log(
            db,
            audit.CONTRACT_PARSED,
            contract_id=contract.id,
            template_id=template.id,
            details={"fields": len(rows)},
        )
        audit.log(
            db,
            audit.COMPARISON_RUN,
            contract_id=contract.id,
            details={
                "completion_percentage": comparison["completion_percentage"],
                "missing": len(comparison["missing_required"]),
                "inconsistencies": len(comparison["inconsistencies"]),
                "fmcsa_violations": len(comparison["fmcsa_violations"]),
                "can_sign": comparison["can_sign"],
            },
        )
        db.commit()
        return {"status": "analyzed", "can_sign": comparison["can_sign"]}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Contract processing failed for %s", contract_id)
        db.rollback()
        contract = db.get(Contract, UUID(contract_id))
        if contract is not None:
            contract.status = "failed"
            contract.error_message = str(exc)[:1000]
            db.commit()
        raise
    finally:
        db.close()
