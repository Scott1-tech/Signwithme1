"""The signing gate and finalisation, over HTTP.

The frontend hides the finalise button when a contract cannot be signed. These
tests cover the control that actually matters: a client posting straight to the
API.
"""
import base64
import io

import pytest
from PIL import Image
from sqlalchemy import select

from tests.conftest import auth


@pytest.fixture
def signature_data_url() -> str:
    image = Image.new("RGBA", (240, 60), (0, 0, 0, 0))
    for x in range(10, 230):
        image.putpixel((x, 30), (0, 0, 0, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _force_signable(api, contract_id: str) -> None:
    """Put the contract in the state a clean review would leave it in."""
    from datetime import datetime, timezone

    from app.models.contract import Contract

    db = api.db_factory()
    try:
        contract = db.get(Contract, __import__("uuid").UUID(contract_id))
        result = dict(contract.comparison_result)
        result.update(
            {"can_sign": True, "missing_required": [], "inconsistencies": [], "fmcsa_violations": []}
        )
        contract.comparison_result = result
        contract.review_status = "approved"
        contract.reviewed_at = datetime.now(timezone.utc)
        contract.status = "signing"
        db.commit()
    finally:
        db.close()


def test_signing_is_refused_while_critical_issues_remain(
    api, contractor_token, uploaded_contract, signature_data_url
):
    response = api.post(
        f"/api/contracts/{uploaded_contract}/signatures",
        headers=auth(contractor_token),
        json={"page": 1, "bbox": {"x": 200, "y": 580, "width": 150, "height": 34},
              "image_data": signature_data_url},
    )
    assert response.status_code == 409
    assert "approved" in response.json()["message"] or "critical" in response.json()["message"]


def test_finalize_is_refused_before_approval(api, contractor_token, uploaded_contract):
    response = api.post(
        f"/api/contracts/{uploaded_contract}/finalize",
        headers=auth(contractor_token),
        json={"contract_date": "2026-08-29"},
    )
    assert response.status_code == 409


def test_a_reviewer_cannot_approve_a_contract_the_engine_blocked(
    api, uploaded_contract, admin_token
):
    """Approval is not an override switch for outstanding critical issues."""
    response = api.post(
        f"/api/review/{uploaded_contract}",
        headers=auth(admin_token),
        json={"decision": "approved", "notes": "looks fine to me"},
    )
    assert response.status_code == 409
    assert "cannot be approved" in response.json()["message"]


def test_review_rejection_is_recorded(api, uploaded_contract, admin_token):
    response = api.post(
        f"/api/review/{uploaded_contract}",
        headers=auth(admin_token),
        json={"decision": "rejected", "notes": "CDL page is unreadable"},
    )
    assert response.status_code == 200
    assert response.json()["review_status"] == "rejected"


def test_finalize_requires_at_least_one_signature(api, contractor_token, uploaded_contract):
    _force_signable(api, uploaded_contract)
    response = api.post(
        f"/api/contracts/{uploaded_contract}/finalize",
        headers=auth(contractor_token),
        json={"contract_date": "2026-08-29"},
    )
    assert response.status_code == 409
    assert "No signatures" in response.json()["message"]


def test_a_corrupt_signature_image_is_rejected(api, contractor_token, uploaded_contract):
    _force_signable(api, uploaded_contract)
    response = api.post(
        f"/api/contracts/{uploaded_contract}/signatures",
        headers=auth(contractor_token),
        json={"page": 1, "bbox": {"x": 200, "y": 580, "width": 150, "height": 34},
              "image_data": "data:image/png;base64,bm90LWFuLWltYWdl"},
    )
    assert response.status_code == 422


def test_the_happy_path_produces_a_hashed_downloadable_pdf(
    api, contractor_token, uploaded_contract, signature_data_url
):
    _force_signable(api, uploaded_contract)

    placed = api.post(
        f"/api/contracts/{uploaded_contract}/signatures",
        headers=auth(contractor_token),
        json={
            "page": 1,
            "bbox": {"x": 200, "y": 580, "width": 150, "height": 34},
            "field_id": "p1_contractor_signature",
            "image_data": signature_data_url,
        },
    )
    assert placed.status_code == 201, placed.text

    finalized = api.post(
        f"/api/contracts/{uploaded_contract}/finalize",
        headers=auth(contractor_token),
        json={"contract_date": "2026-08-29", "apply_paired_dates": True},
    )
    assert finalized.status_code == 200, finalized.text
    body = finalized.json()
    assert len(body["file_hash"]) == 64

    download = api.get(f"/api/download/{uploaded_contract}/final", headers=auth(contractor_token))
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF-")
    assert download.headers["x-content-sha256"] == body["file_hash"]

    verified = api.get(f"/api/download/{uploaded_contract}/verify", headers=auth(contractor_token))
    assert verified.json()["intact"] is True


def test_the_finalised_contract_cannot_be_signed_again(
    api, contractor_token, uploaded_contract, signature_data_url
):
    _force_signable(api, uploaded_contract)
    api.post(
        f"/api/contracts/{uploaded_contract}/signatures",
        headers=auth(contractor_token),
        json={"page": 1, "bbox": {"x": 200, "y": 580, "width": 150, "height": 34},
              "image_data": signature_data_url},
    )
    api.post(
        f"/api/contracts/{uploaded_contract}/finalize",
        headers=auth(contractor_token),
        json={"contract_date": "2026-08-29"},
    )
    again = api.post(
        f"/api/contracts/{uploaded_contract}/signatures",
        headers=auth(contractor_token),
        json={"page": 1, "bbox": {"x": 200, "y": 600, "width": 150, "height": 34},
              "image_data": signature_data_url},
    )
    assert again.status_code == 409


def test_the_audit_trail_records_the_whole_lifecycle(
    api, contractor_token, uploaded_contract, admin_token, signature_data_url
):
    _force_signable(api, uploaded_contract)
    api.post(
        f"/api/contracts/{uploaded_contract}/signatures",
        headers=auth(contractor_token),
        json={"page": 1, "bbox": {"x": 200, "y": 580, "width": 150, "height": 34},
              "image_data": signature_data_url},
    )
    api.post(
        f"/api/contracts/{uploaded_contract}/finalize",
        headers=auth(contractor_token),
        json={"contract_date": "2026-08-29"},
    )
    api.get(f"/api/download/{uploaded_contract}/final", headers=auth(contractor_token))

    trail = api.get(f"/api/review/{uploaded_contract}/audit", headers=auth(admin_token)).json()
    actions = {entry["action"] for entry in trail}
    assert {
        "contract_uploaded",
        "contract_parsed",
        "comparison_run",
        "signature_added",
        "contract_finalized",
        "final_downloaded",
    } <= actions


def test_download_is_refused_to_an_unrelated_contractor(
    api, contractor_token, uploaded_contract, signature_data_url
):
    from tests.conftest import _register

    _force_signable(api, uploaded_contract)
    api.post(
        f"/api/contracts/{uploaded_contract}/signatures",
        headers=auth(contractor_token),
        json={"page": 1, "bbox": {"x": 200, "y": 580, "width": 150, "height": 34},
              "image_data": signature_data_url},
    )
    api.post(
        f"/api/contracts/{uploaded_contract}/finalize",
        headers=auth(contractor_token),
        json={"contract_date": "2026-08-29"},
    )

    stranger = _register(api, "stranger@example.com")
    response = api.get(f"/api/download/{uploaded_contract}/final", headers=auth(stranger))
    assert response.status_code == 403


def test_signatures_are_stored_with_a_hash_and_a_path(
    api, contractor_token, uploaded_contract, signature_data_url
):
    from app.models.signature import Signature

    _force_signable(api, uploaded_contract)
    api.post(
        f"/api/contracts/{uploaded_contract}/signatures",
        headers=auth(contractor_token),
        json={"page": 1, "bbox": {"x": 200, "y": 580, "width": 150, "height": 34},
              "image_data": signature_data_url},
    )
    db = api.db_factory()
    try:
        row = db.scalar(select(Signature))
        assert len(row.signature_hash) == 64
        assert row.signature_image_path in api.objects
    finally:
        db.close()
