from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.common import BBoxModel

Severity = Literal["critical", "warning"]


class MissingField(BaseModel):
    field_id: str
    label: str
    page: int | None = None
    type: str | None = None
    bbox: BBoxModel | None = None
    severity: Severity = "critical"


class Inconsistency(BaseModel):
    type: str
    issue: str
    values: dict[str, object] = {}
    pages: list[int] = []
    field_id: str | None = None
    severity: Severity = "critical"


class FmcsaViolation(BaseModel):
    rule: str
    issue: str
    page: int | None = None
    field_ids: list[str] = []
    severity: Severity = "critical"


class ComparisonOut(BaseModel):
    contract_id: str | None = None
    completion_percentage: float = 0.0
    missing_required: list[MissingField] = []
    inconsistencies: list[Inconsistency] = []
    fmcsa_violations: list[FmcsaViolation] = []
    warnings: list[Inconsistency] = []
    can_sign: bool = False
    field_count: int = 0
    filled_count: int = 0
