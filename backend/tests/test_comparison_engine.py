import pytest

from app.services.comparison_engine import ComparisonEngine

SCHEMA = {
    "pages": [
        {
            "page_number": 1,
            "fields": [
                {"field_id": "p1_full_name", "label": "Full Name", "field_type": "text_line",
                 "page": 1, "required": True, "bbox": {"x": 1, "y": 1, "width": 10, "height": 10}},
                {"field_id": "p1_cdl", "label": "CDL", "field_type": "text_line", "page": 1,
                 "required": True, "bbox": {"x": 1, "y": 20, "width": 10, "height": 10}},
                {"field_id": "p1_email", "label": "Email", "field_type": "text_line", "page": 1,
                 "required": False, "bbox": {"x": 1, "y": 40, "width": 10, "height": 10}},
            ],
        },
        {
            "page_number": 2,
            "fields": [
                {"field_id": "p2_full_legal_name", "label": "Full Legal Name",
                 "field_type": "text_line", "page": 2, "required": True,
                 "bbox": {"x": 1, "y": 1, "width": 10, "height": 10}},
                {"field_id": "p2_cdl_license", "label": "CDL", "field_type": "text_line", "page": 2,
                 "required": True, "bbox": {"x": 1, "y": 20, "width": 10, "height": 10}},
                {"field_id": "p2_dot_eligible", "label": "DOT Eligible", "field_type": "checkbox",
                 "page": 2, "required": True, "bbox": {"x": 1, "y": 40, "width": 10, "height": 10}},
                {"field_id": "p2_cdl_valid", "label": "CDL Valid", "field_type": "checkbox",
                 "page": 2, "required": True, "bbox": {"x": 1, "y": 60, "width": 10, "height": 10}},
            ],
        },
    ]
}


def value(text):
    return {"value": text, "confidence": 1.0, "detected": True}


def complete_data():
    return {
        "p1_full_name": value("CHARLES FRYE"),
        "p1_cdl": value("Oh Rt305248"),
        "p1_email": value("charles@example.com"),
        "p2_full_legal_name": value("Charles Frye"),
        "p2_cdl_license": value("OH-RT305248"),
        "p2_dot_eligible": {"checked": True, "confidence": 0.9, "detected": True},
        "p2_cdl_valid": {"checked": True, "confidence": 0.9, "detected": True},
    }


def test_a_complete_consistent_contract_can_be_signed():
    result = ComparisonEngine().compare(complete_data(), SCHEMA)
    assert result.missing_required == []
    assert result.inconsistencies == []
    assert result.can_sign is True
    assert result.completion_percentage == 100.0


def test_cdl_casing_and_punctuation_do_not_raise_a_false_mismatch():
    """'Oh Rt305248' and 'OH-RT305248' are the same licence. Comparing raw
    strings would block signing on OCR noise."""
    result = ComparisonEngine().compare(complete_data(), SCHEMA)
    assert not [i for i in result.inconsistencies if i["type"] == "cdl_mismatch"]


def test_a_genuine_cdl_mismatch_is_critical():
    data = complete_data()
    data["p2_cdl_license"] = value("TX9999999")
    result = ComparisonEngine().compare(data, SCHEMA)
    mismatch = next(i for i in result.inconsistencies if i["type"] == "cdl_mismatch")
    assert mismatch["severity"] == "critical"
    # Pages are stated explicitly so the review UI can filter without parsing ids.
    assert mismatch["pages"] == [1, 2]
    assert result.can_sign is False


def test_a_middle_name_is_not_a_name_mismatch():
    data = complete_data()
    data["p2_full_legal_name"] = value("Charles A. Frye")
    result = ComparisonEngine().compare(data, SCHEMA)
    assert not [i for i in result.inconsistencies if i["type"] == "name_mismatch"]


def test_a_different_person_is_a_name_mismatch():
    data = complete_data()
    data["p2_full_legal_name"] = value("Maria Lopez")
    result = ComparisonEngine().compare(data, SCHEMA)
    assert [i for i in result.inconsistencies if i["type"] == "name_mismatch"]


def test_missing_required_fields_carry_coordinates():
    """The highlighter cannot draw a box from a label alone."""
    data = complete_data()
    del data["p1_cdl"]
    result = ComparisonEngine().compare(data, SCHEMA)
    missing = next(m for m in result.missing_required if m["field_id"] == "p1_cdl")
    assert missing["bbox"] == {"x": 1, "y": 20, "width": 10, "height": 10}
    assert result.can_sign is False


@pytest.mark.parametrize("field_id", ["p2_dot_eligible", "p2_cdl_valid"])
def test_an_absent_compliance_answer_is_a_violation_not_a_pass(field_id):
    """`if value and value != 'yes'` silently approves a blank box; a blank
    DOT-eligibility answer must fail."""
    data = complete_data()
    del data[field_id]
    result = ComparisonEngine().compare(data, SCHEMA)
    assert [v for v in result.fmcsa_violations if field_id in v["field_ids"]]
    assert result.can_sign is False


def test_rules_for_fields_the_template_lacks_are_skipped():
    """The equipment-experience rule names page-4 fields this template has no
    trace of; asserting on them would fail every contract."""
    result = ComparisonEngine().compare(complete_data(), SCHEMA)
    assert not [v for v in result.fmcsa_violations if v["rule"] == "fmcsa_equipment_experience"]


def test_format_warnings_do_not_block_signing():
    data = complete_data()
    data["p1_email"] = value("not-an-email")
    result = ComparisonEngine().compare(data, SCHEMA)
    assert [w for w in result.warnings if w["field_id"] == "p1_email"]
    assert result.can_sign is True


def test_warnings_use_the_same_shape_as_inconsistencies():
    """One payload shape means the sidebar renders both from one type."""
    data = complete_data()
    data["p1_email"] = value("not-an-email")
    result = ComparisonEngine().compare(data, SCHEMA)
    warning = result.warnings[0]
    assert {"type", "issue", "values", "pages", "severity"} <= set(warning)


def test_completion_percentage_counts_filled_fields():
    data = complete_data()
    del data["p1_email"]
    result = ComparisonEngine().compare(data, SCHEMA)
    assert result.filled_count == 6
    assert result.field_count == 7
    assert result.completion_percentage == pytest.approx(85.7, abs=0.1)
