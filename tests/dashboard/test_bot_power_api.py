from fastapi.testclient import TestClient

from dashboard.api.main import create_app


def _client(monkeypatch, tmp_path, readonly=False):
    monkeypatch.setenv("ARTETA_POWER_FILE", str(tmp_path / "bot_power.json"))
    monkeypatch.setenv("DASHBOARD_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DASHBOARD_WEB_DIST", str(tmp_path / "dist"))
    monkeypatch.setenv("DASHBOARD_READONLY", "true" if readonly else "false")
    return TestClient(create_app())


def test_bot_power_defaults_to_enabled(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.get("/api/bot-power")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["enabled"] is True


def test_bot_power_can_be_disabled_and_reenabled(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    off = client.post("/api/bot-power", json={"enabled": False, "reason": "维护中"})
    assert off.status_code == 200
    assert off.json()["data"]["enabled"] is False
    assert off.json()["data"]["actor"] == "dashboard"
    assert off.json()["data"]["reason"] == "维护中"

    again = client.get("/api/bot-power")
    assert again.json()["data"]["enabled"] is False

    on = client.post("/api/bot-power", json={"enabled": True})
    assert on.status_code == 200
    assert on.json()["data"]["enabled"] is True


def test_bot_power_rejects_writes_in_readonly_mode(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, readonly=True)

    response = client.post("/api/bot-power", json={"enabled": False})

    assert response.status_code == 403


def test_overview_includes_bot_power(monkeypatch, tmp_path):
    import sqlite3

    db_path = tmp_path / "arsenal_data.db"
    env_file = tmp_path / ".env"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE players (user_id TEXT, group_id TEXT, nickname TEXT, level TEXT, favorability INTEGER, last_seen TEXT, profile_json TEXT)"
    )
    conn.execute("CREATE TABLE messages (user_id TEXT, group_id TEXT, message TEXT, timestamp TEXT)")
    conn.commit()
    conn.close()
    env_file.write_text("", encoding="utf-8")

    monkeypatch.setenv("ARTETA_POWER_FILE", str(tmp_path / "bot_power.json"))
    monkeypatch.setenv("ARTETA_DB_PATH", str(db_path))
    monkeypatch.setenv("DASHBOARD_ENV_FILE", str(env_file))
    monkeypatch.setenv("DASHBOARD_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DASHBOARD_WEB_DIST", str(tmp_path / "dist"))

    client = TestClient(create_app())
    response = client.get("/api/overview")

    assert response.status_code == 200
    data = response.json()["data"]
    assert "bot_power" in data
    assert data["bot_power"]["enabled"] is True
