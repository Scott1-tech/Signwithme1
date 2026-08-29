"""Compare an uploaded contract against its template schema.

Produces the payload the review UI renders: what is missing, what disagrees
across pages, which FMCSA rules are violated, and whether signing may proceed.

Two behaviours differ deliberately from a naive implementation:

* Cross-field checks compare *normalised* values. Raw string comparison flags
  'Oh Rt305248' against 'OH-RT305248' as a critical mismatch on OCR noise alone.
* An absent compliance answer is a violation, not a pass. Checking
  `if value and value != 'yes'` silently approves a blank DOT-eligibility box.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field as dc_field

from app.core import pii
from app.services import validators as v

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"


@dataclass
class ComparisonResult:
    contract_id: str | None
    completion_percentage: float
    missing_required: list[dict] = dc_field(default_factory=list)
    inconsistencies: list[dict] = dc_field(default_factory=list)
    fmcsa_violations: list[dict] = dc_field(default_factory=list)
    warnings: list[dict] = dc_field(default_factory=list)
    can_sign: bool = False
    field_count: int = 0
    filled_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CrossFieldRule:
    """Fields that must agree with one another wherever they appear."""

    type: str
    issue: str
    field_ids: list[str]
    normalizer: str = "identifier"  # identifier | name | date | text
    severity: str = SEVERITY_CRITICAL


DEFAULT_CROSS_FIELD_RULES = [
    CrossFieldRule(
        type="cdl_mismatch",
        issue="CDL numbers do not match across pages",
        field_ids=["p1_cdl", "p2_cdl_license", "p2_cdl", "p14_cdl_number", "p14_cdl"],
    ),
    CrossFieldRule(
        type="name_mismatch",
        issue="Contractor name differs between pages",
        field_ids=["p1_full_name", "p2_full_legal_name", "p2_full_name", "p30_full_name"],
        normalizer="name",
    ),
    CrossFieldRule(
        type="exp_date_conflict",
        issue="CDL expiration dates conflict across the document",
        field_ids=["p1_cdl_expiration", "p2_cdl_exp", "p2_cdl_expiration", "p14_expiration_date"],
        normalizer="date",
    ),
    CrossFieldRule(
        type="email_mismatch",
        issue="Contact email differs between pages",
        field_ids=["p1_email", "p2_email"],
        normalizer="text",
        severity=SEVERITY_WARNING,
    ),
]


@dataclass
class FmcsaRule:
    rule: str
    issue: str
    kind: str  # any_affirmative | affirmative | any_filled
    field_ids: list[str]
    page: int
    min_filled: int = 1
    severity: str = SEVERITY_CRITICAL


DEFAULT_FMCSA_RULES = [
    FmcsaRule(
        rule="fmcsa_equipment_experience",
        issue="No equipment driving experience selected. FMCSA requires at least one 'Yes'.",
        kind="any_affirmative",
        field_ids=["p4_straight_truck", "p4_tractor_semi", "p4_tractor_two", "p4_other"],
        page=4,
    ),
    FmcsaRule(
        rule="fmcsa_dot_eligible",
        issue="Contractor is not confirmed DOT eligible.",
        kind="affirmative",
        field_ids=["p2_dot_eligible"],
        page=2,
    ),
    FmcsaRule(
        rule="fmcsa_cdl_valid",
        issue="CDL is not marked as valid and unrestricted.",
        kind="affirmative",
        field_ids=["p2_cdl_valid"],
        page=2,
    ),
    FmcsaRule(
        rule="fmcsa_employment_history",
        issue="No employment history provided. FMCSA requires 3 years of history.",
        kind="any_filled",
        field_ids=["p5_employer_1", "p5_employer_2", "p5_employer_3", "p5_table_1"],
        page=5,
    ),
]

# field_id substring -> format checker
FORMAT_CHECKS = (
    ("email", v.check_email),
    ("cdl", v.check_cdl),
    ("ssn", v.check_ssn),
    ("ein", v.check_ein),
    ("phone", v.check_phone),
)

NORMALIZERS = {
    "identifier": v.normalize_identifier,
    "name": v.normalize_name,
    "text": lambda value: (v.normalize_text(value) or "").upper() or None,
    "date": lambda value: (lambda d: d.isoformat() if d else None)(v.parse_date(value)),
}


class ComparisonEngine:
    def __init__(
        self,
        cross_field_rules: list[CrossFieldRule] | None = None,
        fmcsa_rules: list[FmcsaRule] | None = None,
    ):
        self.cross_field_rules = cross_field_rules or DEFAULT_CROSS_FIELD_RULES
        self.fmcsa_rules = fmcsa_rules or DEFAULT_FMCSA_RULES

    def compare(
        self,
        contract_data: dict,
        template_schema: dict,
        contract_id: str | None = None,
    ) -> ComparisonResult:
        missing: list[dict] = []
        inconsistencies: list[dict] = []
        warnings: list[dict] = []

        field_index = _index_schema(template_schema)
        total = 0
        filled = 0

        for field_id, field in field_index.items():
            total += 1
            extracted = contract_data.get(field_id) or {}
            if self._is_filled(extracted, field):
                filled += 1
            elif field.get("required", False):
                missing.append(
                    {
                        "field_id": field_id,
                        "label": field.get("label", field_id),
                        "page": field.get("page"),
                        "type": field.get("field_type"),
                        # The highlighter needs coordinates, not just a label.
                        "bbox": field.get("bbox"),
                        "severity": SEVERITY_CRITICAL,
                    }
                )

            issue = self._validate_field(extracted, field)
            if issue is not None:
                (inconsistencies if issue["severity"] == SEVERITY_CRITICAL else warnings).append(issue)

        inconsistencies.extend(self._check_cross_field_consistency(contract_data, field_index))
        fmcsa_violations = self._check_fmcsa_compliance(contract_data, field_index)

        completion = (filled / total * 100) if total else 0.0
        can_sign = (
            not any(m["severity"] == SEVERITY_CRITICAL for m in missing)
            and not any(i["severity"] == SEVERITY_CRITICAL for i in inconsistencies)
            and not any(f["severity"] == SEVERITY_CRITICAL for f in fmcsa_violations)
        )

        return ComparisonResult(
            contract_id=contract_id,
            completion_percentage=round(completion, 1),
            missing_required=missing,
            inconsistencies=inconsistencies,
            fmcsa_violations=fmcsa_violations,
            warnings=warnings,
            can_sign=can_sign,
            field_count=total,
            filled_count=filled,
        )

    # -- field level ---------------------------------------------------------

    def _is_filled(self, extracted: dict, field: dict) -> bool:
        if not extracted:
            return False
        field_type = field.get("field_type", "text_line")

        if field_type == "checkbox_group":
            return bool(extracted.get("selected"))
        if field_type == "checkbox":
            return bool(extracted.get("checked"))
        if field_type == "signature":
            return bool(extracted.get("has_signature"))
        if field_type == "table":
            return any(any(cell for cell in row) for row in extracted.get("rows", []))
        return not v.is_blank(extracted.get("value"))

    def _validate_field(self, extracted: dict, field: dict) -> dict | None:
        value = extracted.get("value")
        if v.is_blank(value):
            return None
        if extracted.get("redacted"):
            # Re-running the comparison reads the masked cache; format-checking
            # 'XXX-XX-6789' would invent a warning that is not real.
            return None

        field_id = field["field_id"]
        field_type = field.get("field_type", "text_line")

        error: str | None = None
        if field_type == "date" or _mentions(field_id, "date", "exp", "dob", "birth"):
            error = v.check_date(value)
        if error is None:
            for token, checker in FORMAT_CHECKS:
                if _mentions(field_id, token):
                    error = checker(value)
                    if error:
                        break

        if error is None:
            return None

        # Same shape as cross-field issues, so the frontend has one type to render.
        return {
            "type": f"invalid_{field_id}",
            "field_id": field_id,
            "issue": error,
            "values": {field_id: pii.mask(value, field_id)},
            "pages": [field.get("page")],
            "severity": SEVERITY_WARNING,
        }

    # -- cross field ---------------------------------------------------------

    def _check_cross_field_consistency(self, contract_data: dict, field_index: dict) -> list[dict]:
        issues: list[dict] = []
        for rule in self.cross_field_rules:
            normalize = NORMALIZERS[rule.normalizer]
            present: dict[str, str] = {}
            normalized: dict[str, str] = {}
            for field_id in rule.field_ids:
                raw = (contract_data.get(field_id) or {}).get("value")
                if v.is_blank(raw):
                    continue
                present[field_id] = raw
                key = normalize(raw)
                if key:
                    normalized[field_id] = key

            if len(normalized) < 2:
                continue

            if rule.normalizer == "name":
                values = list(present.values())
                agrees = all(v.names_match(values[0], other) for other in values[1:])
            else:
                agrees = len(set(normalized.values())) == 1

            if not agrees:
                issues.append(
                    {
                        "type": rule.type,
                        "issue": rule.issue,
                        "values": pii.redact_mapping(present),
                        # Explicit pages so the review UI can filter without
                        # parsing field-id prefixes.
                        "pages": sorted(
                            {field_index.get(fid, {}).get("page") for fid in present}
                            - {None}
                        ),
                        "severity": rule.severity,
                    }
                )
        return issues

    # -- FMCSA ---------------------------------------------------------------

    def _check_fmcsa_compliance(self, contract_data: dict, field_index: dict) -> list[dict]:
        violations: list[dict] = []
        for rule in self.fmcsa_rules:
            known = [fid for fid in rule.field_ids if fid in field_index]
            if not known:
                # The template does not carry these fields; the rule cannot apply.
                continue

            satisfied = False
            if rule.kind == "any_affirmative":
                satisfied = any(self._affirmative(contract_data.get(fid)) for fid in known)
            elif rule.kind == "affirmative":
                satisfied = all(self._affirmative(contract_data.get(fid)) for fid in known)
            elif rule.kind == "any_filled":
                filled = sum(
                    1
                    for fid in known
                    if self._is_filled(contract_data.get(fid) or {}, field_index[fid])
                )
                satisfied = filled >= rule.min_filled

            if not satisfied:
                violations.append(
                    {
                        "rule": rule.rule,
                        "issue": rule.issue,
                        "page": rule.page,
                        "field_ids": known,
                        "severity": rule.severity,
                    }
                )
        return violations

    def _affirmative(self, extracted: dict | None) -> bool:
        """Missing data is never affirmative -- a blank compliance box fails."""
        if not extracted:
            return False
        if extracted.get("checked"):
            return True
        selected = extracted.get("selected") or []
        if any(str(option).lower() in {"yes", "y"} for option in selected):
            return True
        return v.is_affirmative(extracted.get("value"))


def _index_schema(template_schema: dict) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for page in template_schema.get("pages", []):
        page_number = page.get("page_number")
        for field in page.get("fields", []):
            entry = dict(field)
            entry.setdefault("page", page_number)
            index[field["field_id"]] = entry
    return index


def _mentions(field_id: str, *tokens: str) -> bool:
    parts = set(field_id.lower().split("_"))
    return any(token in parts or token in field_id.lower() for token in tokens)
