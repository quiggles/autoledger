"""
tests/test_auth.py
------------------
Tests for first-run onboarding, login/logout, the API access guard, and the
guarantee that no secret is ever exposed through a GET.
"""

from tests.conftest import TEST_PASSWORD, TEST_USERNAME

# ── Onboarding gate ────────────────────────────────────────────────────────────

def test_status_reports_not_onboarded_initially(anon_client):
    body = anon_client.get("/api/auth/status").get_json()
    assert body["onboarded"] is False
    assert body["authenticated"] is False


def test_protected_route_blocked_before_onboarding(anon_client):
    # No account yet → 403 with onboarding_required so the SPA forces onboarding.
    resp = anon_client.get("/api/vehicles")
    assert resp.status_code == 403
    assert resp.get_json()["onboarding_required"] is True


def test_onboard_creates_admin_and_logs_in(anon_client):
    resp = anon_client.post(
        "/api/auth/onboard", json={"username": "admin", "password": "supersecret1"}
    )
    assert resp.status_code == 201
    # Session is established by onboarding — protected routes now reachable.
    assert anon_client.get("/api/vehicles").status_code == 200
    status = anon_client.get("/api/auth/status").get_json()
    assert status["onboarded"] is True
    assert status["authenticated"] is True
    assert status["username"] == "admin"


def test_onboard_rejects_short_password(anon_client):
    resp = anon_client.post(
        "/api/auth/onboard", json={"username": "admin", "password": "short"}
    )
    assert resp.status_code == 400


def test_onboard_twice_is_rejected(anon_client):
    anon_client.post("/api/auth/onboard", json={"username": "a", "password": "password123"})
    second = anon_client.post(
        "/api/auth/onboard", json={"username": "b", "password": "password123"}
    )
    assert second.status_code == 409


# ── Login / logout ─────────────────────────────────────────────────────────────

def test_login_with_correct_password(client):
    # `client` is already onboarded + logged in; log out then back in.
    client.post("/api/auth/logout")
    assert client.get("/api/vehicles").status_code == 401
    resp = client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200
    assert client.get("/api/vehicles").status_code == 200


def test_login_with_wrong_password_is_401(client):
    client.post("/api/auth/logout")
    resp = client.post(
        "/api/auth/login", json={"username": TEST_USERNAME, "password": "wrong"}
    )
    assert resp.status_code == 401


def test_logout_clears_session(client):
    assert client.get("/api/vehicles").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/vehicles").status_code == 401


# ── No secret leakage ──────────────────────────────────────────────────────────

def test_status_never_returns_password_hash(client):
    body = client.get("/api/auth/status").get_json()
    assert "password_hash" not in body
    assert "password" not in body
