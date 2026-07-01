from fastapi.testclient import TestClient

from dashboard.api.main import create_app


def test_health_returns_ok():
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "healthy"


def test_login_and_me_do_not_require_password_or_token(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    monkeypatch.delenv("DASHBOARD_SECRET_KEY", raising=False)
    client = TestClient(create_app())

    login = client.post("/api/auth/login", json={"password": "wrong"})
    me = client.get("/api/auth/me")

    assert login.status_code == 200
    assert login.json()["data"]["token"] == ""
    assert me.status_code == 200
    assert me.json()["data"]["subject"] == "admin"
