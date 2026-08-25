from dashboard.api.security import create_access_token, decode_access_token, verify_admin_password


def test_verify_admin_password_requires_configured_password(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    assert verify_admin_password("secret") is True
    assert verify_admin_password("wrong") is False


def test_verify_admin_password_rejects_when_unconfigured(monkeypatch):
    monkeypatch.delenv("DASHBOARD_ADMIN_PASSWORD", raising=False)
    assert verify_admin_password("") is False
    assert verify_admin_password("anything") is False


def test_token_round_trip(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    token = create_access_token({"sub": "admin"})
    payload = decode_access_token(token)
    assert payload["sub"] == "admin"
