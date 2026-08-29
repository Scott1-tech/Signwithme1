import io

import pdfplumber
import pytest
from PIL import Image
from pypdf import PdfReader

from app.services.geometry import BBox
from app.services.pdf_builder import DatePlacement, PdfBuilder, SignaturePlacement


@pytest.fixture
def signature_png() -> bytes:
    image = Image.new("RGBA", (240, 60), (0, 0, 0, 0))
    for x in range(10, 230):
        image.putpixel((x, 30 + (x % 7)), (0, 0, 0, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_date_is_rendered_us_style_not_iso(blank_template_bytes):
    """The date input submits 2026-08-29; the contract prints 08/29/2026."""
    result = PdfBuilder().build_final_contract(
        blank_template_bytes,
        signatures=[],
        dates=[DatePlacement(page=1, bbox=BBox(440, 590, 100, 14), value="2026-08-29")],
    )
    with pdfplumber.open(io.BytesIO(result.pdf_bytes)) as pdf:
        text = pdf.pages[0].extract_text()
    assert "08/29/2026" in text
    assert "2026-08-29" not in text


def test_overlay_lands_at_the_requested_position(blank_template_bytes):
    """A box 590pt from the top of a 792pt page must draw near y=202 in
    reportlab's bottom-left space -- not at y=590, which would mirror it."""
    result = PdfBuilder().build_final_contract(
        blank_template_bytes,
        signatures=[],
        dates=[DatePlacement(page=1, bbox=BBox(440, 590, 100, 14), value="08/29/2026")],
    )
    with pdfplumber.open(io.BytesIO(result.pdf_bytes)) as pdf:
        words = pdf.pages[0].extract_words()
    drawn = next(w for w in words if "08/29/2026" in w["text"])
    assert abs(float(drawn["top"]) - 590) < 12
    assert abs(float(drawn["x0"]) - 440) < 12


def test_signature_image_is_embedded_on_the_right_page(blank_template_bytes, signature_png):
    result = PdfBuilder().build_final_contract(
        blank_template_bytes,
        signatures=[
            SignaturePlacement(
                page=1, bbox=BBox(200, 580, 150, 34), image_bytes=signature_png, field_id="p1_sig"
            )
        ],
        dates=[],
    )
    with pdfplumber.open(io.BytesIO(result.pdf_bytes)) as pdf:
        images = pdf.pages[0].images
    assert images, "the signature image should be present on page 1"
    placed = images[0]
    assert abs(float(placed["top"]) - 580) < 20


def test_page_size_comes_from_the_page_not_a_hardcoded_letter():
    """An A4 page overlaid with letter geometry shifts every mark."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.drawString(72, 700, "A4 PAGE")
    pdf.showPage()
    pdf.save()

    result = PdfBuilder().build_final_contract(
        buffer.getvalue(),
        signatures=[],
        dates=[DatePlacement(page=1, bbox=BBox(100, 500, 100, 14), value="08/29/2026")],
    )
    with pdfplumber.open(io.BytesIO(result.pdf_bytes)) as pdf_out:
        page = pdf_out.pages[0]
        assert round(page.height) == round(A4[1])
        drawn = next(w for w in page.extract_words() if "08/29/2026" in w["text"])
        assert abs(float(drawn["top"]) - 500) < 12


def test_result_is_hashed_for_the_audit_trail(blank_template_bytes):
    builder = PdfBuilder()
    result = builder.build_final_contract(blank_template_bytes, [], [])
    assert len(result.sha256) == 64
    assert result.page_count == 1


def test_owner_password_locks_the_signed_document(blank_template_bytes):
    result = PdfBuilder().build_final_contract(
        blank_template_bytes, [], [], owner_password="secret"
    )
    reader = PdfReader(io.BytesIO(result.pdf_bytes))
    assert reader.is_encrypted
