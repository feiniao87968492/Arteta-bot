import json
import sqlite3

from fastapi.testclient import TestClient

from dashboard.api.main import app
from dashboard.api.security import create_access_token


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE players (user_id TEXT, group_id TEXT, nickname TEXT, level TEXT, favorability INTEGER, last_seen TEXT, profile_json TEXT)")
    conn.execute("CREATE TABLE messages (user_id TEXT, group_id TEXT, message TEXT, timestamp TEXT)")
    conn.execute("CREATE TABLE nicknames (user_id TEXT, group_id TEXT, nickname TEXT, first_seen TEXT, last_seen TEXT)")
    conn.execute("CREATE TABLE member_relations (user_id TEXT, target_user_id TEXT, group_id TEXT, interaction_count INTEGER, last_interaction_time TEXT)")
    conn.execute("INSERT INTO players VALUES (?, ?, ?, ?, ?, ?, ?)", ("u1", "g1", "Saka", "核心首发", 230, "2026-05-22", json.dumps({"personality": "冷静"}, ensure_ascii=False)))
    conn.commit()
    conn.close()


def _client(monkeypatch, tmp_path, readonly=False):
    db_path = tmp_path / "arsenal_data.db"
    _make_db(str(db_path))
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "secret")
    monkeypatch.setenv("DASHBOARD_READONLY", "true" if readonly else "false")
    monkeypatch.setenv("ARTETA_DB_PATH", str(db_path))
    monkeypatch.setattr("dashboard.api.config.REPO_ROOT", str(tmp_path))
    token = create_access_token({"sub": "admin"})
    return TestClient(app), {"Authorization": f"Bearer {token}"}, db_path


def test_update_user_profile_endpoint(monkeypatch, tmp_path):
    client, headers, db_path = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/groups/g1/users/u1/profile",
        headers=headers,
        json={"profile": {"personality": "更衣室领袖", "interests": "战术板"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["personality_profile"]["personality"] == "更衣室领袖"

    conn = sqlite3.connect(str(db_path))
    stored = conn.execute("SELECT profile_json FROM players WHERE group_id = ? AND user_id = ?", ("g1", "u1")).fetchone()[0]
    conn.close()
    assert json.loads(stored)["interests"] == "战术板"


def test_delete_user_profile_endpoint_clears_profile_json(monkeypatch, tmp_path):
    client, headers, db_path = _client(monkeypatch, tmp_path)

    response = client.delete("/api/groups/g1/users/u1/profile", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["personality_profile"] == {}

    conn = sqlite3.connect(str(db_path))
    stored = conn.execute("SELECT profile_json FROM players WHERE group_id = ? AND user_id = ?", ("g1", "u1")).fetchone()[0]
    conn.close()
    assert stored == "{}"


def test_profile_write_endpoints_respect_readonly(monkeypatch, tmp_path):
    client, headers, _db_path = _client(monkeypatch, tmp_path, readonly=True)

    response = client.post("/api/groups/g1/users/u1/profile", headers=headers, json={"profile": {"personality": "x"}})

    assert response.status_code == 403


def test_list_groups_includes_memory_password_status(monkeypatch, tmp_path):
    client, headers, _db_path = _client(monkeypatch, tmp_path)

    response = client.get("/api/groups", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"][0]["memory_password_enabled"] is False
    assert response.json()["data"][0]["group_name"] == ""


def test_update_group_name_endpoint(monkeypatch, tmp_path):
    client, headers, _db_path = _client(monkeypatch, tmp_path)

    response = client.post("/api/groups/g1/settings/name", headers=headers, json={"group_name": "阿森纳更衣室"})

    assert response.status_code == 200
    assert response.json()["data"] == {"group_id": "g1", "group_name": "阿森纳更衣室"}
    list_response = client.get("/api/groups", headers=headers)
    assert list_response.json()["data"][0]["group_name"] == "阿森纳更衣室"


def test_set_and_clear_group_password_endpoints(monkeypatch, tmp_path):
    client, headers, db_path = _client(monkeypatch, tmp_path)

    set_response = client.post("/api/groups/g1/settings/password", headers=headers, json={"password": "team-secret"})

    assert set_response.status_code == 200
    assert set_response.json()["data"] == {"group_id": "g1", "memory_password_enabled": True}
    list_response = client.get("/api/groups", headers=headers)
    assert list_response.json()["data"][0]["memory_password_enabled"] is True

    conn = sqlite3.connect(str(db_path))
    stored = conn.execute("SELECT password_hash FROM dashboard_group_settings WHERE group_id = ?", ("g1",)).fetchone()[0]
    conn.close()
    assert "team-secret" not in stored

    clear_response = client.request("DELETE", "/api/groups/g1/settings/password", headers=headers, json={"password": "team-secret"})

    assert clear_response.status_code == 200
    assert clear_response.json()["data"] == {"group_id": "g1", "memory_password_enabled": False}
    audit_text = (tmp_path / "logs" / "dashboard_audit.log").read_text(encoding="utf-8")
    assert "action=group.password.set" in audit_text
    assert "action=group.password.clear" in audit_text


def test_group_password_endpoints_validate_input_and_readonly(monkeypatch, tmp_path):
    client, headers, _db_path = _client(monkeypatch, tmp_path)

    blank_response = client.post("/api/groups/g1/settings/password", headers=headers, json={"password": "   "})

    assert blank_response.status_code == 400

    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    readonly_client, readonly_headers, _readonly_db_path = _client(monkeypatch, readonly_dir, readonly=True)

    set_response = readonly_client.post("/api/groups/g1/settings/password", headers=readonly_headers, json={"password": "team-secret"})
    clear_response = readonly_client.request("DELETE", "/api/groups/g1/settings/password", headers=readonly_headers, json={"password": "team-secret"})

    assert set_response.status_code == 403
    assert clear_response.status_code == 403


def test_clear_group_password_requires_existing_password(monkeypatch, tmp_path):
    client, headers, _db_path = _client(monkeypatch, tmp_path)
    client.post("/api/groups/g1/settings/password", headers=headers, json={"password": "team-secret"})

    missing_response = client.request("DELETE", "/api/groups/g1/settings/password", headers=headers, json={})
    wrong_response = client.request("DELETE", "/api/groups/g1/settings/password", headers=headers, json={"password": "wrong"})
    ok_response = client.request("DELETE", "/api/groups/g1/settings/password", headers=headers, json={"password": "team-secret"})

    assert missing_response.status_code == 403
    assert wrong_response.status_code == 403
    assert ok_response.status_code == 200
    assert ok_response.json()["data"] == {"group_id": "g1", "memory_password_enabled": False}


def test_protected_group_profile_reads_require_password(monkeypatch, tmp_path):
    client, headers, _db_path = _client(monkeypatch, tmp_path)
    client.post("/api/groups/g1/settings/password", headers=headers, json={"password": "team-secret"})

    missing_users = client.get("/api/groups/g1/users", headers=headers)
    wrong_users = client.get("/api/groups/g1/users", headers={**headers, "X-Group-Password": "wrong"})
    ok_users = client.get("/api/groups/g1/users", headers={**headers, "X-Group-Password": "team-secret"})
    missing_detail = client.get("/api/groups/g1/users/u1", headers=headers)
    ok_detail = client.get("/api/groups/g1/users/u1", headers={**headers, "X-Group-Password": "team-secret"})

    assert missing_users.status_code == 403
    assert wrong_users.status_code == 403
    assert ok_users.status_code == 200
    assert ok_users.json()["data"][0]["user_id"] == "u1"
    assert missing_detail.status_code == 403
    assert ok_detail.status_code == 200
    assert ok_detail.json()["data"]["user_id"] == "u1"


def test_protected_group_profile_writes_require_password(monkeypatch, tmp_path):
    client, headers, _db_path = _client(monkeypatch, tmp_path)
    client.post("/api/groups/g1/settings/password", headers=headers, json={"password": "team-secret"})

    missing_update = client.post("/api/groups/g1/users/u1/profile", headers=headers, json={"profile": {"personality": "x"}})
    wrong_update = client.post("/api/groups/g1/users/u1/profile", headers=headers, json={"profile": {"personality": "x"}, "password": "wrong"})
    ok_update = client.post("/api/groups/g1/users/u1/profile", headers=headers, json={"profile": {"personality": "x"}, "password": "team-secret"})
    missing_delete = client.request("DELETE", "/api/groups/g1/users/u1/profile", headers=headers, json={"password": "wrong"})
    ok_delete = client.request("DELETE", "/api/groups/g1/users/u1/profile", headers=headers, json={"password": "team-secret"})

    assert missing_update.status_code == 403
    assert wrong_update.status_code == 403
    assert ok_update.status_code == 200
    assert missing_delete.status_code == 403
    assert ok_delete.status_code == 200


def test_update_user_favor_set_value(monkeypatch, tmp_path):
    client, headers, db_path = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/groups/g1/users/u1/favor",
        headers=headers,
        json={"favor": 320},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["favorability"] == 320
    assert data["level"] == "核心首发"

    conn = sqlite3.connect(str(db_path))
    fav, level = conn.execute("SELECT favorability, level FROM players WHERE group_id = ? AND user_id = ?", ("g1", "u1")).fetchone()
    conn.close()
    assert fav == 320
    assert level == "核心首发"


def test_update_user_favor_delta_creates_player(monkeypatch, tmp_path):
    client, headers, db_path = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/groups/g1/users/u-new/favor",
        headers=headers,
        json={"delta": 60, "nickname": "新球员"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["favorability"] == 60
    assert data["level"] == "一线队"

    conn = sqlite3.connect(str(db_path))
    fav, level, nickname = conn.execute(
        "SELECT favorability, level, nickname FROM players WHERE group_id = ? AND user_id = ?",
        ("g1", "u-new"),
    ).fetchone()
    conn.close()
    assert fav == 60
    assert level == "一线队"
    assert nickname == "新球员"


def test_update_user_favor_validation_errors(monkeypatch, tmp_path):
    client, headers, _db_path = _client(monkeypatch, tmp_path)

    both_response = client.post(
        "/api/groups/g1/users/u1/favor",
        headers=headers,
        json={"favor": 100, "delta": 5},
    )
    none_response = client.post(
        "/api/groups/g1/users/u1/favor",
        headers=headers,
        json={},
    )
    zero_delta_response = client.post(
        "/api/groups/g1/users/u1/favor",
        headers=headers,
        json={"delta": 0},
    )

    assert both_response.status_code == 400
    assert none_response.status_code == 400
    assert zero_delta_response.status_code == 400


def test_update_user_favor_blocked_in_readonly(monkeypatch, tmp_path):
    client, headers, _db_path = _client(monkeypatch, tmp_path, readonly=True)

    response = client.post(
        "/api/groups/g1/users/u1/favor",
        headers=headers,
        json={"favor": 50},
    )

    assert response.status_code == 403
