import json
import sqlite3

from fastapi.testclient import TestClient

from dashboard.api.main import create_app


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE players (user_id TEXT, group_id TEXT, nickname TEXT, level TEXT, favorability INTEGER, last_seen TEXT, profile_json TEXT)"
    )
    conn.execute("CREATE TABLE messages (user_id TEXT, group_id TEXT, message TEXT, timestamp TEXT)")
    conn.execute(
        "INSERT INTO players VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("u1", "g1", "Saka", "核心首发", 230, "2026-05-22", "{}"),
    )
    conn.execute("INSERT INTO messages VALUES (?, ?, ?, ?)", ("u1", "g1", "hello", "2026-05-22 10:00:00"))
    conn.commit()
    conn.close()


def _auth_headers(client):
    login = client.post("/api/auth/login", json={"password": "secret"})
    assert login.status_code == 200
    token = login.json()["data"]["token"]
    return {"Authorization": "Bearer " + token}


def test_overview_returns_mission_control_summary_without_real_chroma(monkeypatch, tmp_path):
    db_path = tmp_path / "arsenal_data.db"
    env_file = tmp_path / ".env"
    chroma_dir = tmp_path / "missing_chroma"
    _make_db(str(db_path))
    env_file.write_text("DEEPSEEK_API_KEY=sk-abcdef123456\n", encoding="utf-8")

    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    monkeypatch.setenv("ARTETA_DB_PATH", str(db_path))
    monkeypatch.setenv("ARTETA_CHROMA_DIR", str(chroma_dir))
    monkeypatch.setenv("DASHBOARD_ENV_FILE", str(env_file))

    client = TestClient(create_app())
    response = client.get("/api/overview", headers=_auth_headers(client))

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    data = body["data"]
    assert set(["paths", "groups", "chroma", "logs", "config", "latest_report", "readonly"]).issubset(data)
    assert data["paths"]["db"]["exists"] is True
    assert data["paths"]["chroma"]["exists"] is False
    assert data["groups"]["count"] == 1
    assert data["groups"]["items"][0]["group_id"] == "g1"
    assert data["chroma"]["available"] is False
    assert data["config"]["keys"][0]["name"] == "DEEPSEEK_API_KEY"
def test_overview_returns_ecs_sync_status(monkeypatch, tmp_path):
    db_path = tmp_path / "arsenal_data.db"
    env_file = tmp_path / ".env"
    status_path = tmp_path / "ecs_sync_status.json"
    _make_db(str(db_path))
    env_file.write_text("", encoding="utf-8")
    status_path.write_text(
        json.dumps(
            {
                "ok": True,
                "last_success_at": "2020-01-01T00:00:00+00:00",
                "last_error": "",
                "remote_db": "/opt/arteta_bot/arsenal_data.db",
                "local_db": str(db_path),
                "bytes": 123,
                "duration_ms": 42,
                "interval_seconds": 10,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    monkeypatch.setenv("ARTETA_DB_PATH", str(db_path))
    monkeypatch.setenv("DASHBOARD_ENV_FILE", str(env_file))
    monkeypatch.setenv("DASHBOARD_SYNC_STATUS_PATH", str(status_path))

    client = TestClient(create_app())
    response = client.get("/api/overview", headers=_auth_headers(client))

    assert response.status_code == 200
    sync = response.json()["data"]["sync"]
    assert sync["available"] is True
    assert sync["stale"] is True
    assert sync["last_error"] == ""
    assert sync["remote_db"] == "/opt/arteta_bot/arsenal_data.db"
    assert sync["bytes"] == 123
