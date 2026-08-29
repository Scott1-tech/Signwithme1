"""Overlay signatures and dates onto the uploaded contract to produce the final
legally binding document.

Three details that a naive overlay gets wrong, and are handled here:

* Page size is read from each page's own mediabox. Hardcoding `letter` shifts
  every overlay on a legal or A4 page.
* Canonical bounding boxes use a top-left origin (pdfplumber); reportlab draws
  from the bottom left. The conversion happens once, in `_draw_page`.
* Pages carrying /Rotate need their overlay rotated to match, or the signature
  lands sideways.
"""
from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.services.geometry import BBox, rotate_for_page
from app.services.validators import format_date

logger = logging.getLogger(__name__)

DATE_FONT = "Helvetica"
DATE_FONT_SIZE = 11.0


@dataclass
class SignaturePlacement:
    page: int  # 1-indexed
    bbox: BBox  # canonical: points, top-left origin
    image_bytes: bytes
    field_id: str | None = None


@dataclass
class DatePlacement:
    page: int
    bbox: BBox
    value: str  # rendered as MM/DD/YYYY regardless of the input format
    field_id: str | None = None


@dataclass
class BuildResult:
    pdf_bytes: bytes
    sha256: str
    page_count: int


class PdfBuilder:
    def build_final_contract(
        self,
        source_pdf: bytes,
        signatures: list[SignaturePlacement],
        dates: list[DatePlacement],
        *,
        title: str = "Signed Independent Contractor Agreement",
        author: str = "Cargo Freight Trucking Inc",
        owner_password: str | None = None,
    ) -> BuildResult:
        # Cloning into the writer up front keeps every page attached to it, which
        # is what pypdf requires for merge_page (and is mandatory from pypdf 7).
        writer = PdfWriter(clone_from=io.BytesIO(source_pdf))

        sigs_by_page: dict[int, list[SignaturePlacement]] = {}
        dates_by_page: dict[int, list[DatePlacement]] = {}
        for placement in signatures:
            sigs_by_page.setdefault(placement.page - 1, []).append(placement)
        for placement in dates:
            dates_by_page.setdefault(placement.page - 1, []).append(placement)

        page_count = len(writer.pages)
        for index, page in enumerate(writer.pages):
            page_sigs = sigs_by_page.get(index, [])
            page_dates = dates_by_page.get(index, [])
            if page_sigs or page_dates:
                page.merge_page(self._draw_page(page, page_sigs, page_dates))

        writer.add_metadata(
            {
                "/Title": title,
                "/Author": author,
                "/Creator": "Contract Signing App",
                "/Producer": "Contract Signing App v1.0",
                "/CreationDate": datetime.now(timezone.utc).strftime("D:%Y%m%d%H%M%SZ"),
            }
        )

        if owner_password:
            # Readable by anyone holding the document, but not editable without
            # the owner password -- the signed artefact should not be alterable.
            writer.encrypt(user_password="", owner_password=owner_password)

        buffer = io.BytesIO()
        writer.write(buffer)
        pdf_bytes = buffer.getvalue()
        return BuildResult(
            pdf_bytes=pdf_bytes,
            sha256=hashlib.sha256(pdf_bytes).hexdigest(),
            page_count=page_count,
        )

    # -- overlay -------------------------------------------------------------

    def _draw_page(self, page, signatures: list[SignaturePlacement], dates: list[DatePlacement]):
        box = page.mediabox
        width = float(box.width)
        height = float(box.height)
        rotation = int(page.get("/Rotate") or 0) % 360

        # A rotated page is displayed with its dimensions swapped; the overlay
        # canvas must match the *displayed* geometry.
        if rotation in (90, 270):
            canvas_size = (height, width)
            unrotated = (height, width)
        else:
            canvas_size = (width, height)
            unrotated = (width, height)

        packet = io.BytesIO()
        pdf_canvas = canvas.Canvas(packet, pagesize=canvas_size)

        for placement in signatures:
            bbox = rotate_for_page(placement.bbox, unrotated[0], unrotated[1], rotation)
            self._draw_signature(pdf_canvas, bbox, placement, canvas_size[1])

        for placement in dates:
            bbox = rotate_for_page(placement.bbox, unrotated[0], unrotated[1], rotation)
            self._draw_date(pdf_canvas, bbox, placement, canvas_size[1])

        pdf_canvas.save()
        packet.seek(0)
        overlay_page = PdfReader(packet).pages[0]
        if rotation:
            overlay_page.rotate(rotation)
        return overlay_page

    def _draw_signature(
        self, pdf_canvas, bbox: BBox, placement: SignaturePlacement, page_height: float
    ) -> None:
        x, y, width, height = bbox.to_reportlab(page_height)
        image = ImageReader(io.BytesIO(placement.image_bytes))
        pdf_canvas.drawImage(
            image,
            x,
            y,
            width=width,
            height=height,
            preserveAspectRatio=True,
            anchor="sw",
            mask="auto",
        )

    def _draw_date(self, pdf_canvas, bbox: BBox, placement: DatePlacement, page_height: float) -> None:
        x, y, _, height = bbox.to_reportlab(page_height)
        try:
            text = format_date(placement.value)
        except ValueError:
            text = str(placement.value)
        pdf_canvas.setFont(DATE_FONT, DATE_FONT_SIZE)
        pdf_canvas.setFillColorRGB(0, 0, 0)
        # Sit the baseline inside the field box rather than on its lower edge.
        baseline = y + max((height - DATE_FONT_SIZE) / 2.0, 1.0)
        pdf_canvas.drawString(x + 2.0, baseline, text)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
