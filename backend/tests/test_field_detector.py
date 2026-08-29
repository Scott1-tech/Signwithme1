from app.services.field_detector import FieldDetector
from app.services.geometry import BBox


def test_detects_the_labelled_text_fields(blank_template_path):
    schema = FieldDetector().build_schema(blank_template_path)
    ids = {f["field_id"] for page in schema["pages"] for f in page["fields"]}
    assert "p1_full_name" in ids
    assert "p1_cdl" in ids
    assert "p1_email" in ids


def test_bboxes_are_real_coordinates_not_placeholders(blank_template_path):
    """Every downstream feature -- highlighting and signature overlay alike --
    depends on these being derived from actual word positions."""
    schema = FieldDetector().build_schema(blank_template_path)
    fields = [f for page in schema["pages"] for f in page["fields"]]
    assert fields
    for field in fields:
        box = BBox.from_dict(field["bbox"])
        assert box.width > 0 and box.height > 0
        assert not (box.x == 0 and box.y == 0 and box.width == 100 and box.height == 20)

    name = next(f for f in fields if f["field_id"] == "p1_full_name")
    box = BBox.from_dict(name["bbox"])
    # The fill region follows the label, which is drawn at x=72.
    assert box.x > 72


def test_signature_and_date_are_typed_and_paired(blank_template_path):
    schema = FieldDetector().build_schema(blank_template_path)
    fields = {f["field_id"]: f for page in schema["pages"] for f in page["fields"]}
    signature = next(f for f in fields.values() if f["field_type"] == "signature")
    assert signature["paired_date_field_id"] is not None
    assert fields[signature["paired_date_field_id"]]["field_type"] == "date"


def test_vector_square_checkboxes_are_detected(blank_template_path):
    """Base-14 fonts carry no U+2610 glyph, so many templates draw checkboxes as
    rectangles. Matching only the ballot-box character would miss them, and a
    missed checkbox is a missed required field."""
    schema = FieldDetector().build_schema(blank_template_path)
    boxes = [
        f
        for page in schema["pages"]
        for f in page["fields"]
        if f["field_type"] == "checkbox" and f["detector"] == "checkbox_rect"
    ]
    assert len(boxes) >= 3
    labels = {f["label"] for f in boxes}
    assert "Individual" in labels and "LLC" in labels


def test_ballot_box_glyphs_form_a_checkbox_group():
    """The glyph path, exercised directly: templates that do emit U+2610 should
    produce one group with every option, not three loose checkboxes."""
    from app.services.field_detector import _Line, _Word
    from app.services.geometry import BBox

    texts = ["W-9", "Status:", "\u2610", "Individual", "\u2610", "LLC"]
    words = [
        _Word(text=text, bbox=BBox(x=72.0 + index * 40, y=560.0, width=30.0, height=10.0))
        for index, text in enumerate(texts)
    ]
    line = _Line(words=words)
    cursor = 0
    for index, word in enumerate(words):
        line.offsets.append((cursor, cursor + len(word.text), index))
        cursor += len(word.text) + 1
    line.text = " ".join(texts)

    fields = FieldDetector()._detect_checkboxes(line, page_number=1, counters={})
    assert len(fields) == 1
    group = fields[0]
    assert group.field_type == "checkbox_group"
    assert [option["label"] for option in group.options] == ["Individual", "LLC"]
    assert group.validation_rule == "at_least_one"


def test_repeated_labels_do_not_collapse_into_one_field():
    """'Date:' appears beside every signature. Suffixing keeps the contractor
    and company-rep dates distinct instead of deduplicating them away."""
    detector = FieldDetector()
    counters: dict[str, int] = {}
    first = detector._unique_id(1, "date", counters)
    second = detector._unique_id(1, "date", counters)
    assert first == "p1_date"
    assert second == "p1_date_2"


def test_pages_carry_their_dimensions(blank_template_path):
    schema = FieldDetector().build_schema(blank_template_path)
    page = schema["pages"][0]
    assert round(page["width"]) == 612 and round(page["height"]) == 792
