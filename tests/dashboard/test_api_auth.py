from fastapi.testclient import TestClient

from dashboard.api.main import create_app


def test_health_returns_ok():
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "healthy"


def test_login_requires_the_configured_dashboard_password(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    monkeypatch.delenv("DASHBOARD_SECRET_KEY", raising=False)
    client = TestClient(create_app())

    rejected = client.post("/api/auth/login", json={"password": "wrong"})
    accepted = client.post("/api/auth/login", json={"password": "secret"})

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["data"]["token"]
