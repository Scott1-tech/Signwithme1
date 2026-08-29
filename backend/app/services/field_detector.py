"""Detect fillable regions in a blank template PDF.

Unlike a text-only scan, every field produced here carries a real bounding box
derived from word positions returned by pdfplumber -- highlighting in the review
UI and signature placement in the final PDF both depend on those coordinates
being correct.

Label patterns are supplied per template rather than hardcoded, so a second
template can be onboarded without editing this module. The defaults match the
Cargo Freight Trucking driver contract.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field as dc_field
from typing import Any, Iterable

import pdfplumber

from app.services.geometry import BBox

CHECKBOX_GLYPHS = "☐□❑❏⬜◻▫"
CHECKBOX_RE = re.compile(f"[{CHECKBOX_GLYPHS}]")

# Minimum width given to a fill region when no underscore run follows the label.
MIN_FILL_WIDTH = 90.0
DEFAULT_FILL_HEIGHT = 14.0
SIGNATURE_HEIGHT = 34.0


@dataclass
class FieldRegion:
    field_id: str
    label: str
    field_type: str  # text_line | checkbox | checkbox_group | signature | date | table
    page: int
    bbox: dict
    required: bool = True
    options: list[dict] | None = None
    validation_rule: str | None = None
    # Links a signature field to the date field that accompanies it, so the
    # frontend never has to guess the pairing by string substitution.
    paired_date_field_id: str | None = None
    detector: str = "text"

    def to_dict(self) -> dict:
        data = asdict(self)
        if data["options"] is None:
            data.pop("options")
        return data


@dataclass
class LabelPattern:
    pattern: str
    name: str
    field_type: str = "text_line"
    required: bool = True

    @property
    def regex(self) -> re.Pattern:
        return re.compile(self.pattern, re.IGNORECASE)


DEFAULT_LABEL_PATTERNS: list[LabelPattern] = [
    LabelPattern(r"Full\s+(?:Legal\s+)?Name\s*:", "full_name"),
    LabelPattern(r"\bCDL\s*(?:Number|#)?\s*:", "cdl"),
    LabelPattern(r"\bState\s*:", "state"),
    LabelPattern(r"\bExp(?:iration)?(?:\s+Date)?\s*:", "cdl_expiration", "date"),
    LabelPattern(r"Date\s+of\s+Birth\s*:", "date_of_birth", "date"),
    LabelPattern(r"\bPhone\s*:", "phone"),
    LabelPattern(r"\bEmail\s*:", "email"),
    LabelPattern(r"\bSSN\s*:", "ssn"),
    LabelPattern(r"EIN\s*(?:\(if applicable\))?\s*:", "ein", required=False),
    LabelPattern(r"Effective\s+Date\s+of\s+Agreement\s*:", "effective_date", "date"),
    LabelPattern(r"Unit\s+Assigned\s*:", "unit_assigned", required=False),
    LabelPattern(r"Address\s*:", "address", required=False),
    LabelPattern(r"Contractor\s+Signature\s*:", "contractor_signature", "signature"),
    LabelPattern(r"Company\s+Representative\s+Signature\s*:", "company_rep_signature", "signature"),
    LabelPattern(r"(?<!\w)Signature\s*:", "signature", "signature"),
    LabelPattern(r"(?<!\w)Date\s*:", "date", "date"),
]


@dataclass
class _Word:
    text: str
    bbox: BBox


@dataclass
class _Line:
    words: list[_Word]
    text: str = ""
    # Character offset -> index into `words`, so a regex match maps back to boxes.
    offsets: list[tuple[int, int, int]] = dc_field(default_factory=list)

    @property
    def bbox(self) -> BBox:
        box = self.words[0].bbox
        for word in self.words[1:]:
            box = box.union(word.bbox)
        return box

    def words_in_span(self, start: int, end: int) -> list[_Word]:
        return [self.words[i] for (s, e, i) in self.offsets if s < end and e > start]

    def span_bbox(self, start: int, end: int) -> BBox | None:
        words = self.words_in_span(start, end)
        if not words:
            return None
        box = words[0].bbox
        for word in words[1:]:
            box = box.union(word.bbox)
        return box


class FieldDetector:
    def __init__(self, label_patterns: list[LabelPattern] | None = None):
        self.label_patterns = label_patterns or DEFAULT_LABEL_PATTERNS

    # -- public API ----------------------------------------------------------

    def analyze_template(self, pdf_path: str) -> list[FieldRegion]:
        fields: list[FieldRegion] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                fields.extend(self._analyze_page(page, page_number))
        fields = self._pair_signatures_with_dates(fields)
        return self._sort(fields)

    def build_schema(self, pdf_path: str) -> dict:
        """Detector output in the JSONB shape stored on templates.field_schema."""
        fields = self.analyze_template(pdf_path)
        with pdfplumber.open(pdf_path) as pdf:
            pages_meta = [
                {"page_number": i, "width": float(p.width), "height": float(p.height),
                 "rotation": int(p.rotation or 0)}
                for i, p in enumerate(pdf.pages, start=1)
            ]
        by_page: dict[int, list[dict]] = {}
        for region in fields:
            by_page.setdefault(region.page, []).append(region.to_dict())
        return {
            "pages": [
                {**meta, "fields": by_page.get(meta["page_number"], [])} for meta in pages_meta
            ],
            "field_count": len(fields),
        }

    # -- per page ------------------------------------------------------------

    def _analyze_page(self, page, page_number: int) -> list[FieldRegion]:
        lines = self._build_lines(page)
        page_width, page_height = float(page.width), float(page.height)

        fields: list[FieldRegion] = []
        counters: dict[str, int] = {}

        for line in lines:
            fields.extend(self._detect_line_fields(line, page_number, page_width, counters))
            fields.extend(self._detect_checkboxes(line, page_number, counters))

        fields.extend(self._detect_rect_checkboxes(page, page_number, lines, counters))
        fields.extend(self._detect_tables(page, page_number, page_height))
        return fields

    def _build_lines(self, page) -> list[_Line]:
        words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
        buckets: dict[int, list[dict]] = {}
        for word in words:
            # Cluster words onto a shared baseline; 3pt buckets tolerate jitter.
            key = int(round(float(word["top"]) / 3.0))
            buckets.setdefault(key, []).append(word)

        lines: list[_Line] = []
        for key in sorted(buckets):
            raw = sorted(buckets[key], key=lambda w: float(w["x0"]))
            line = _Line(words=[
                _Word(
                    text=w["text"],
                    bbox=BBox.from_pdfplumber(w["x0"], w["top"], w["x1"], w["bottom"]),
                )
                for w in raw
            ])
            cursor = 0
            parts: list[str] = []
            for index, word in enumerate(line.words):
                start = cursor
                parts.append(word.text)
                cursor += len(word.text)
                line.offsets.append((start, cursor, index))
                cursor += 1  # the joining space
            line.text = " ".join(parts)
            lines.append(line)
        return lines

    # -- text / signature / date fields --------------------------------------

    def _detect_line_fields(
        self, line: _Line, page_number: int, page_width: float, counters: dict[str, int]
    ) -> list[FieldRegion]:
        matches: list[tuple[int, int, LabelPattern]] = []
        for pattern in self.label_patterns:
            for match in pattern.regex.finditer(line.text):
                matches.append((match.start(), match.end(), pattern))
        if not matches:
            return []

        # Longer, more specific labels win over the generic fallbacks that
        # overlap them ("Contractor Signature:" beats "Signature:").
        matches.sort(key=lambda m: (m[0], -(m[1] - m[0])))
        chosen: list[tuple[int, int, LabelPattern]] = []
        for start, end, pattern in matches:
            if any(start < c_end and end > c_start for c_start, c_end, _ in chosen):
                continue
            chosen.append((start, end, pattern))
        chosen.sort(key=lambda m: m[0])

        fields: list[FieldRegion] = []
        for index, (start, end, pattern) in enumerate(chosen):
            label_box = line.span_bbox(start, end)
            if label_box is None:
                continue
            next_start = chosen[index + 1][0] if index + 1 < len(chosen) else None
            fill_box = self._fill_region(line, end, next_start, label_box, page_width, pattern)
            fields.append(
                FieldRegion(
                    field_id=self._unique_id(page_number, pattern.name, counters),
                    label=line.text[start:end].strip(" :"),
                    field_type=pattern.field_type,
                    page=page_number,
                    bbox=fill_box.to_dict(),
                    required=pattern.required,
                )
            )
        return fields

    def _fill_region(
        self,
        line: _Line,
        label_end: int,
        next_label_start: int | None,
        label_box: BBox,
        page_width: float,
        pattern: LabelPattern,
    ) -> BBox:
        """The writable area following a label, bounded by the next label on the line."""
        limit = next_label_start if next_label_start is not None else len(line.text)
        trailing = line.text[label_end:limit]

        height = SIGNATURE_HEIGHT if pattern.field_type == "signature" else max(
            label_box.height, DEFAULT_FILL_HEIGHT
        )

        underscores = re.search(r"_{2,}", trailing)
        if underscores:
            span_start = label_end + underscores.start()
            span_end = label_end + underscores.end()
            run = line.span_bbox(span_start, span_end)
            if run is not None:
                # A signature sits on the rule, not under it.
                top = run.y - height if pattern.field_type == "signature" else run.y - height / 2
                return BBox(x=run.x, y=max(top, 0.0), width=run.width, height=height)

        right_edge = page_width - 36.0
        if next_label_start is not None:
            neighbour = line.span_bbox(next_label_start, next_label_start + 1)
            if neighbour is not None:
                right_edge = neighbour.x - 4.0
        width = max(right_edge - label_box.x1 - 4.0, MIN_FILL_WIDTH)
        top = label_box.y - (height - label_box.height) if pattern.field_type == "signature" else label_box.y
        return BBox(x=label_box.x1 + 4.0, y=max(top, 0.0), width=width, height=height)

    # -- checkboxes ----------------------------------------------------------

    def _detect_checkboxes(
        self, line: _Line, page_number: int, counters: dict[str, int]
    ) -> list[FieldRegion]:
        glyphs = list(CHECKBOX_RE.finditer(line.text))
        if not glyphs:
            return []

        label_part = line.text[: glyphs[0].start()].strip(" :")
        group_label = label_part or "Options"

        options: list[dict] = []
        for index, glyph in enumerate(glyphs):
            end = glyphs[index + 1].start() if index + 1 < len(glyphs) else len(line.text)
            option_label = line.text[glyph.end() : end].strip(" :,;")
            box = line.span_bbox(glyph.start(), end) or line.span_bbox(glyph.start(), glyph.end())
            glyph_box = line.span_bbox(glyph.start(), glyph.end())
            if box is None or glyph_box is None:
                continue
            options.append(
                {
                    "id": _slugify(option_label) or f"option_{index + 1}",
                    "label": option_label,
                    "bbox": glyph_box.to_dict(),
                    "region_bbox": box.to_dict(),
                }
            )

        if not options:
            return []

        group_box = line.bbox
        if len(options) == 1:
            return [
                FieldRegion(
                    field_id=self._unique_id(page_number, _slugify(options[0]["label"]), counters),
                    label=options[0]["label"] or group_label,
                    field_type="checkbox",
                    page=page_number,
                    bbox=options[0]["bbox"],
                    required=False,
                    detector="checkbox_glyph",
                )
            ]
        return [
            FieldRegion(
                field_id=self._unique_id(page_number, _slugify(group_label), counters),
                label=group_label,
                field_type="checkbox_group",
                page=page_number,
                bbox=group_box.to_dict(),
                required=True,
                options=options,
                validation_rule="at_least_one",
                detector="checkbox_glyph",
            )
        ]

    def _detect_rect_checkboxes(
        self, page, page_number: int, lines: list[_Line], counters: dict[str, int]
    ) -> list[FieldRegion]:
        """Fallback for templates that draw checkboxes as vector squares rather
        than emitting a U+2610 glyph."""
        squares: list[BBox] = []
        for rect in page.rects:
            width = float(rect["x1"]) - float(rect["x0"])
            height = float(rect["bottom"]) - float(rect["top"])
            if 5.0 <= width <= 18.0 and 5.0 <= height <= 18.0 and abs(width - height) <= 3.0:
                squares.append(BBox.from_pdfplumber(rect["x0"], rect["top"], rect["x1"], rect["bottom"]))
        if not squares:
            return []

        fields: list[FieldRegion] = []
        for square in squares:
            label, label_box = self._label_right_of(square, lines)
            if label_box is None:
                continue
            fields.append(
                FieldRegion(
                    field_id=self._unique_id(page_number, _slugify(label) or "checkbox", counters),
                    label=label,
                    field_type="checkbox",
                    page=page_number,
                    bbox=square.to_dict(),
                    required=False,
                    detector="checkbox_rect",
                )
            )
        return fields

    def _label_right_of(self, square: BBox, lines: list[_Line]) -> tuple[str, BBox | None]:
        best: tuple[float, str, BBox] | None = None
        for line in lines:
            for word in line.words:
                vertical_gap = abs(word.bbox.y - square.y)
                horizontal_gap = word.bbox.x - square.x1
                if vertical_gap <= 6.0 and 0 <= horizontal_gap <= 60.0:
                    if best is None or horizontal_gap < best[0]:
                        best = (horizontal_gap, word.text, word.bbox)
        if best is None:
            return "", None
        return best[1], best[2]

    # -- tables --------------------------------------------------------------

    def _detect_tables(self, page, page_number: int, page_height: float) -> list[FieldRegion]:
        fields: list[FieldRegion] = []
        try:
            tables = page.find_tables()
        except Exception:  # pdfplumber raises on some malformed pages
            return fields

        for index, table in enumerate(tables):
            x0, top, x1, bottom = table.bbox
            rows = len(table.rows) if getattr(table, "rows", None) else 0
            fields.append(
                FieldRegion(
                    field_id=f"p{page_number}_table_{index + 1}",
                    label=f"Table {index + 1}",
                    field_type="table",
                    page=page_number,
                    bbox=BBox.from_pdfplumber(x0, top, x1, bottom).to_dict(),
                    required=False,
                    validation_rule="at_least_one_row",
                    detector="table",
                )
            )
            _ = rows
        return fields

    # -- assembly ------------------------------------------------------------

    def _pair_signatures_with_dates(self, fields: list[FieldRegion]) -> list[FieldRegion]:
        """Associate each signature with the nearest date field to its right on
        the same page, so date placement uses real coordinates rather than a
        fixed pixel offset from the signature."""
        by_page: dict[int, list[FieldRegion]] = {}
        for region in fields:
            by_page.setdefault(region.page, []).append(region)

        for page_fields in by_page.values():
            dates = [f for f in page_fields if f.field_type == "date"]
            claimed: set[str] = set()
            for signature in (f for f in page_fields if f.field_type == "signature"):
                sig_box = BBox.from_dict(signature.bbox)
                candidates = []
                for candidate in dates:
                    if candidate.field_id in claimed:
                        continue
                    box = BBox.from_dict(candidate.bbox)
                    if abs(box.y - sig_box.y) > 40.0:
                        continue
                    candidates.append((abs(box.x - sig_box.x1), candidate))
                if candidates:
                    candidates.sort(key=lambda pair: pair[0])
                    chosen = candidates[0][1]
                    signature.paired_date_field_id = chosen.field_id
                    claimed.add(chosen.field_id)
        return fields

    def _unique_id(self, page_number: int, name: str, counters: dict[str, int]) -> str:
        base = f"p{page_number}_{name}"
        counters[base] = counters.get(base, 0) + 1
        occurrence = counters[base]
        # 'Date:' appears beside every signature; suffixing keeps the contractor
        # and company-rep dates from collapsing into one field.
        return base if occurrence == 1 else f"{base}_{occurrence}"

    def _sort(self, fields: Iterable[FieldRegion]) -> list[FieldRegion]:
        return sorted(fields, key=lambda f: (f.page, f.bbox["y"], f.bbox["x"]))


def _slugify(text: str | Any) -> str:
    return re.sub(r"[^\w]+", "_", str(text or "").lower()).strip("_")[:60]
