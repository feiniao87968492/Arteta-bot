from fastapi.testclient import TestClient

from dashboard.api.main import create_app
from dashboard.api.routers import config as config_router


def _auth_headers(client):
    login = client.post("/api/auth/login", json={"password": "secret"})
    assert login.status_code == 200
    token = login.json()["data"]["token"]
    return {"Authorization": "Bearer " + token}


def test_config_update_is_immediately_effective_in_dashboard_api(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_MODEL=old-model\n", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    monkeypatch.setenv("DASHBOARD_ENV_FILE", str(env_file))
    monkeypatch.setenv("DEEPSEEK_MODEL", "old-model")

    client = TestClient(create_app())
    headers = _auth_headers(client)

    update = client.post(
        "/api/config/keys",
        headers=headers,
        json={"name": "DEEPSEEK_MODEL", "value": "deepseek-v4-flash"},
    )
    assert update.status_code == 200

    check = client.get("/api/config/keys/DEEPSEEK_MODEL/test", headers=headers)
    assert check.status_code == 200
    data = check.json()["data"]
    assert data["effective"] is True
    assert data["file_value"] == "deepseek-v4-flash"
    assert data["runtime_value"] == "deepseek-v4-flash"
    assert data["requires_bot_restart"] is True


def test_config_test_rejects_non_whitelisted_key(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    monkeypatch.setenv("DASHBOARD_ENV_FILE", str(env_file))

    client = TestClient(create_app())
    response = client.get("/api/config/keys/NOT_ALLOWED/test", headers=_auth_headers(client))

    assert response.status_code == 400


def test_config_restart_bot_runs_fixed_supervisor_command(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    monkeypatch.setenv("DASHBOARD_ENV_FILE", str(env_file))
    monkeypatch.setenv("DASHBOARD_READONLY", "false")
    calls = []

    class Result:
        returncode = 0
        stdout = "arteta_bot: restarted\n"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr(config_router.subprocess, "run", fake_run)

    client = TestClient(create_app())
    response = client.post("/api/config/restart-bot", headers=_auth_headers(client))

    assert response.status_code == 200
    assert calls == [
        (
            ["supervisorctl", "restart", "arteta_bot"],
            {"capture_output": True, "text": True, "timeout": 30},
        )
    ]
    data = response.json()["data"]
    assert data["service"] == "arteta_bot"
    assert data["returncode"] == 0


def test_config_restart_bot_rejects_readonly_mode(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    monkeypatch.setenv("DASHBOARD_ENV_FILE", str(env_file))
    monkeypatch.setenv("DASHBOARD_READONLY", "true")
    called = False

    def fake_run(command, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(config_router.subprocess, "run", fake_run)

    client = TestClient(create_app())
    response = client.post("/api/config/restart-bot", headers=_auth_headers(client))

    assert response.status_code == 403
    assert called is False
