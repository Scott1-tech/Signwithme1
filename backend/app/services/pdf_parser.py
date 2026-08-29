"""Extract filled values from an uploaded contract, guided by a template schema.

For each field in the template we crop the corresponding region of the uploaded
PDF and read whatever the contractor put there. Signatures are detected by the
presence of non-text content (an embedded image or vector strokes) inside the
region -- which is how DocuSign and most e-sign tools stamp a signature.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field as dc_field
from typing import Any

import pdfplumber

from app.services.geometry import BBox
from app.services.validators import is_blank, normalize_text

logger = logging.getLogger(__name__)

# Crops are padded slightly: contractors rarely write exactly inside the ruled box.
CROP_PADDING = 2.0
SIGNATURE_MIN_STROKES = 4
SIGNATURE_MIN_IMAGE_AREA_RATIO = 0.05


@dataclass
class ExtractedField:
    field_id: str
    field_type: str
    page: int
    value: str | None = None
    confidence: float = 0.0
    detected: bool = False
    selected: list[str] = dc_field(default_factory=list)
    checked: bool = False
    has_signature: bool = False
    rows: list[list[str]] = dc_field(default_factory=list)
    extra: dict = dc_field(default_factory=dict)

    def to_dict(self) -> dict:
        data: dict[str, Any] = {
            "value": self.value,
            "confidence": round(self.confidence, 2),
            "detected": self.detected,
        }
        if self.field_type in ("checkbox_group",):
            data["selected"] = self.selected
        if self.field_type == "checkbox":
            data["checked"] = self.checked
        if self.field_type == "signature":
            data["has_signature"] = self.has_signature
        if self.field_type == "table":
            data["rows"] = self.rows
        if self.extra:
            data["extra"] = self.extra
        return data


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PdfParser:
    def page_count(self, pdf_path: str) -> int:
        with pdfplumber.open(pdf_path) as pdf:
            return len(pdf.pages)

    def extract(self, pdf_path: str, field_schema: dict) -> dict[str, dict]:
        """Return {field_id: extracted-dict} for every field in the schema."""
        results: dict[str, dict] = {}
        with pdfplumber.open(pdf_path) as pdf:
            for page_schema in field_schema.get("pages", []):
                page_number = int(page_schema.get("page_number", 0))
                if not 1 <= page_number <= len(pdf.pages):
                    continue
                page = pdf.pages[page_number - 1]
                context = _PageContext(page)
                for field in page_schema.get("fields", []):
                    try:
                        extracted = self._extract_field(context, field, page_number)
                    except Exception:  # never let one bad region abort the document
                        logger.exception("Failed to extract field %s", field.get("field_id"))
                        extracted = ExtractedField(
                            field_id=field.get("field_id", "unknown"),
                            field_type=field.get("field_type", "text_line"),
                            page=page_number,
                        )
                    results[extracted.field_id] = extracted.to_dict()
        return results

    # -- per field -----------------------------------------------------------

    def _extract_field(self, context: "_PageContext", field: dict, page_number: int) -> ExtractedField:
        field_id = field["field_id"]
        field_type = field.get("field_type", "text_line")
        bbox = BBox.from_dict(field["bbox"])
        result = ExtractedField(field_id=field_id, field_type=field_type, page=page_number)

        if field_type == "signature":
            result.has_signature, result.confidence = context.has_ink(bbox)
            result.detected = result.has_signature
            return result

        if field_type == "checkbox":
            result.checked, result.confidence = context.is_checked(bbox)
            result.detected = result.checked
            return result

        if field_type == "checkbox_group":
            for option in field.get("options", []):
                checked, _ = context.is_checked(BBox.from_dict(option["bbox"]))
                if checked:
                    result.selected.append(option["id"])
            result.detected = bool(result.selected)
            result.confidence = 0.9 if result.selected else 0.0
            result.value = ", ".join(result.selected) or None
            return result

        if field_type == "table":
            result.rows = context.table_rows(bbox)
            result.detected = any(any(cell for cell in row) for row in result.rows)
            result.confidence = 0.8 if result.detected else 0.0
            return result

        text, confidence = context.text_in(bbox)
        result.value = normalize_text(text)
        result.confidence = confidence
        result.detected = not is_blank(result.value)
        if not result.detected:
            result.value = None
        return result


class _PageContext:
    """Cached per-page views so each field crop does not re-walk the page."""

    def __init__(self, page):
        self.page = page
        self.width = float(page.width)
        self.height = float(page.height)

    def _crop(self, bbox: BBox):
        x0 = max(bbox.x - CROP_PADDING, 0.0)
        top = max(bbox.y - CROP_PADDING, 0.0)
        x1 = min(bbox.x1 + CROP_PADDING, self.width)
        bottom = min(bbox.y1 + CROP_PADDING, self.height)
        if x1 <= x0 or bottom <= top:
            return None
        return self.page.crop((x0, top, x1, bottom), strict=False)

    def text_in(self, bbox: BBox) -> tuple[str | None, float]:
        crop = self._crop(bbox)
        if crop is None:
            return None, 0.0
        text = crop.extract_text() or ""
        # The ruled fill line extracts as underscores interleaved with whatever
        # was written on top of it ('_C__H_A_R_L_E__S_ F_R__Y_E___'), so they are
        # removed outright rather than turned into spaces -- real word breaks
        # survive as actual space characters.
        text = text.replace("_", "")
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return None, 0.0
        # Digital text is exact; confidence only drops below 1.0 for OCR output.
        return text, 1.0

    def has_ink(self, bbox: BBox) -> tuple[bool, float]:
        """A signature region counts as signed when it holds an embedded image
        or a meaningful number of vector strokes."""
        for image in self.page.images:
            image_box = BBox.from_pdfplumber(image["x0"], image["top"], image["x1"], image["bottom"])
            if image_box.overlaps(bbox):
                overlap_area = _intersection_area(image_box, bbox)
                if overlap_area / max(bbox.width * bbox.height, 1.0) >= SIGNATURE_MIN_IMAGE_AREA_RATIO:
                    return True, 0.95

        strokes = 0
        for shape in list(self.page.curves) + list(self.page.lines):
            shape_box = BBox.from_pdfplumber(shape["x0"], shape["top"], shape["x1"], shape["bottom"])
            if not shape_box.overlaps(bbox):
                continue
            # A ruled signature line is wide and flat; ignore it.
            if shape_box.height < 2.0 and shape_box.width > bbox.width * 0.5:
                continue
            strokes += 1
        if strokes >= SIGNATURE_MIN_STROKES:
            return True, 0.8

        # Some tools stamp a typed name instead of an image.
        text, _ = self.text_in(bbox)
        if text and len(text) >= 3:
            return True, 0.6
        return False, 0.0

    def is_checked(self, bbox: BBox) -> tuple[bool, float]:
        """A checkbox is marked when something was drawn or typed inside it."""
        for char in self.page.chars:
            char_box = BBox.from_pdfplumber(char["x0"], char["top"], char["x1"], char["bottom"])
            if not char_box.overlaps(bbox):
                continue
            text = (char.get("text") or "").strip()
            if text in {"x", "X", "✓", "✔", "☑", "☒", "■", "●"}:
                return True, 0.95
        for shape in list(self.page.curves) + list(self.page.lines):
            shape_box = BBox.from_pdfplumber(shape["x0"], shape["top"], shape["x1"], shape["bottom"])
            if shape_box.overlaps(bbox) and shape_box.width < bbox.width * 1.5:
                # Ignore the box outline itself: it matches the region exactly.
                if abs(shape_box.width - bbox.width) > 2.0 or abs(shape_box.height - bbox.height) > 2.0:
                    return True, 0.7
        return False, 0.0

    def table_rows(self, bbox: BBox) -> list[list[str]]:
        crop = self._crop(bbox)
        if crop is None:
            return []
        try:
            tables = crop.extract_tables()
        except Exception:
            return []
        rows: list[list[str]] = []
        for table in tables:
            for row in table:
                rows.append([(cell or "").strip() for cell in row])
        return rows


def _intersection_area(a: BBox, b: BBox) -> float:
    width = max(0.0, min(a.x1, b.x1) - max(a.x, b.x))
    height = max(0.0, min(a.y1, b.y1) - max(a.y, b.y))
    return width * height
