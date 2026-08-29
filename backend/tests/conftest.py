"""Synthetic PDFs so the detector and parser can be tested without shipping a
real driver contract (which contains personal data)."""
from __future__ import annotations

import io

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

PAGE_WIDTH, PAGE_HEIGHT = letter


def _draw_common(pdf, filled: bool):
    pdf.setFont("Helvetica", 11)
    pdf.drawString(72, 720, "INDEPENDENT CONTRACTOR AGREEMENT")

    rows = [
        (680, "Full Name:", "CHARLES FRYE"),
        (660, "CDL:", "Oh Rt305248"),
        (640, "Exp:", "01/30/2030"),
        (620, "Email:", "charles@example.com"),
        (600, "SSN:", "123-45-6789"),
    ]
    for y, label, value in rows:
        pdf.drawString(72, y, label)
        pdf.drawString(200, y, "_" * 30)
        if filled:
            pdf.drawString(205, y + 3, value)

    # Checkboxes drawn as vector squares -- the common real-world case. Base-14
    # fonts have no U+2610 glyph, so a template authored in Word or reportlab
    # emits rectangles, not ballot-box characters.
    pdf.drawString(72, 560, "W-9 Status:")
    for index, (x, label) in enumerate(((150, "Individual"), (260, "Sole Proprietor"), (390, "LLC"))):
        pdf.rect(x, 558, 10, 10, stroke=1, fill=0)
        pdf.drawString(x + 14, 560, label)
        if filled and index == 0:
            pdf.drawString(x + 2, 560, "X")

    # Signature line with an accompanying date on the same row.
    pdf.drawString(72, 200, "Contractor Signature:")
    pdf.drawString(200, 200, "_" * 25)
    pdf.drawString(400, 200, "Date:")
    pdf.drawString(440, 200, "_" * 15)


def _make_pdf(filled: bool, pages: int = 1) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    for _ in range(pages):
        _draw_common(pdf, filled)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


@pytest.fixture
def blank_template_bytes() -> bytes:
    return _make_pdf(filled=False)


@pytest.fixture
def filled_contract_bytes() -> bytes:
    return _make_pdf(filled=True)


@pytest.fixture
def blank_template_path(tmp_path, blank_template_bytes) -> str:
    path = tmp_path / "template.pdf"
    path.write_bytes(blank_template_bytes)
    return str(path)


@pytest.fixture
def filled_contract_path(tmp_path, filled_contract_bytes) -> str:
    path = tmp_path / "contract.pdf"
    path.write_bytes(filled_contract_bytes)
    return str(path)
