"""Authentication, roles and throttling, exercised through the real routes."""
from tests.conftest import auth


def test_registration_always_creates_a_contractor(api):
    """Self-service registration must not be able to mint an admin."""
    response = api.post(
        "/api/auth/register",
        json={
            "email": "sneaky@example.com",
            "password": "password123",
            "full_name": "Sneaky",
            "role": "admin",
        },
    )
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "contractor"


def test_login_rejects_a_wrong_password_without_confirming_the_account_exists(api, contractor_token):
    known = api.post("/api/auth/login", json={"email": "driver@example.com", "password": "wrong"})
    unknown = api.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong"})
    assert known.status_code == unknown.status_code == 401
    assert known.json()["message"] == unknown.json()["message"]


def test_repeated_failures_are_throttled(api, contractor_token):
    """The login form is the one endpoint reachable with no credentials."""
    last = None
    for _ in range(12):
        last = api.post("/api/auth/login", json={"email": "driver@example.com", "password": "wrong"})
    assert last is not None and last.status_code == 429
    # A correct password is refused too while the lockout stands.
    blocked = api.post(
        "/api/auth/login", json={"email": "driver@example.com", "password": "password123"}
    )
    assert blocked.status_code == 429


def test_protected_routes_reject_an_absent_or_bad_token(api):
    assert api.get("/api/contracts").status_code == 401
    assert api.get("/api/contracts", headers=auth("not-a-jwt")).status_code == 401


def test_template_upload_requires_admin(api, contractor_token, blank_template_bytes):
    response = api.post(
        "/api/templates",
        headers=auth(contractor_token),
        files={"file": ("t.pdf", blank_template_bytes, "application/pdf")},
        data={"name": "Nope"},
    )
    assert response.status_code == 403
