import json
import sqlite3

from dashboard.api.services.sqlite_service import SQLiteService


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE players (user_id TEXT, group_id TEXT, nickname TEXT, level TEXT, favorability INTEGER, last_seen TEXT, profile_json TEXT)")
    conn.execute("CREATE TABLE messages (user_id TEXT, group_id TEXT, message TEXT, timestamp TEXT)")
    conn.execute("CREATE TABLE daily_messages (user_id TEXT, group_id TEXT, nickname TEXT, message TEXT, timestamp TEXT)")
    conn.execute("CREATE TABLE nicknames (user_id TEXT, group_id TEXT, nickname TEXT, first_seen TEXT, last_seen TEXT)")
    conn.execute("CREATE TABLE profile_updates (user_id TEXT, group_id TEXT, old_profile TEXT, new_profile TEXT, trigger_message TEXT, timestamp TEXT)")
    conn.execute("CREATE TABLE member_relations (user_id TEXT, target_user_id TEXT, group_id TEXT, interaction_count INTEGER, last_interaction_time TEXT)")
    conn.execute("INSERT INTO players VALUES (?, ?, ?, ?, ?, ?, ?)", ("u1", "g1", "Saka", "核心首发", 230, "2026-05-22", json.dumps({"style": "winger"})))
    conn.execute("INSERT INTO messages VALUES (?, ?, ?, ?)", ("u1", "g1", "hello", "2026-05-22 10:00:00"))
    conn.execute("INSERT INTO nicknames VALUES (?, ?, ?, ?, ?)", ("u1", "g1", "Starboy", "2026-05-01", "2026-05-22"))
    conn.commit()
    conn.close()


def test_list_groups(tmp_path):
    db_path = tmp_path / "arsenal_data.db"
    _make_db(str(db_path))
    service = SQLiteService(str(db_path))
    groups = service.list_groups()
    assert groups[0]["group_id"] == "g1"
    assert groups[0]["group_name"] == ""
    assert groups[0]["user_count"] == 1
    assert groups[0]["message_count"] == 1
    assert groups[0]["memory_password_enabled"] is False


def test_list_groups_includes_group_names(tmp_path):
    db_path = tmp_path / "arsenal_data.db"
    _make_db(str(db_path))
    service = SQLiteService(str(db_path))

    service.upsert_group_name("g1", "阿森纳更衣室")

    groups = service.list_groups()
    assert groups[0]["group_id"] == "g1"
    assert groups[0]["group_name"] == "阿森纳更衣室"


def test_list_groups_includes_groups_that_only_have_messages(tmp_path):
    db_path = tmp_path / "arsenal_data.db"
    _make_db(str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO messages VALUES (?, ?, ?, ?)", ("u2", "491603775", "first message", "2026-05-23 11:00:00"))
    conn.commit()
    conn.close()

    groups = SQLiteService(str(db_path)).list_groups()

    assert {row["group_id"] for row in groups} == {"g1", "491603775"}
    missing_group = next(row for row in groups if row["group_id"] == "491603775")
    assert missing_group["user_count"] == 1
    assert missing_group["message_count"] == 1


def test_list_groups_includes_groups_that_only_have_daily_messages(tmp_path):
    db_path = tmp_path / "arsenal_data.db"
    _make_db(str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO daily_messages VALUES (?, ?, ?, ?, ?)", ("u2", "491603775", "Highbury", "daily only", "2026-05-23 11:00:00"))
    conn.commit()
    conn.close()

    groups = SQLiteService(str(db_path)).list_groups()

    daily_group = next(row for row in groups if row["group_id"] == "491603775")
    assert daily_group["user_count"] == 1
    assert daily_group["message_count"] == 1


def test_list_users_includes_users_from_daily_messages(tmp_path):
    db_path = tmp_path / "arsenal_data.db"
    _make_db(str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO daily_messages VALUES (?, ?, ?, ?, ?)", ("u2", "491603775", "Highbury", "daily only", "2026-05-23 11:00:00"))
    conn.commit()
    conn.close()

    users = SQLiteService(str(db_path)).list_users("491603775")

    assert users == [{"user_id": "u2", "group_id": "491603775", "nickname": "Highbury", "level": "", "favorability": 0, "last_seen": None, "message_count": 1}]


def test_user_detail(tmp_path):
    db_path = tmp_path / "arsenal_data.db"
    _make_db(str(db_path))
    service = SQLiteService(str(db_path))
    detail = service.get_user_detail("g1", "u1")
    assert detail["user"]["nickname"] == "Saka"
    assert detail["profile"]["style"] == "winger"
    assert detail["nicknames"][0]["nickname"] == "Starboy"


def test_user_detail_matches_profile_command_shape(tmp_path):
    db_path = tmp_path / "arsenal_data.db"
    _make_db(str(db_path))

    detail = SQLiteService(str(db_path)).get_user_detail("g1", "u1")

    assert detail["current_nickname"] == "Saka"
    assert detail["level"] == "核心首发"
    assert detail["favorability"] == 230
    assert detail["message_count"] == 1
    assert detail["personality_profile"] == {"style": "winger"}
    assert detail["recent_messages"] == [{"message": "hello", "timestamp": "2026-05-22 10:00:00"}]


def test_user_detail_uses_latest_profile_update_when_player_profile_is_empty(tmp_path):
    db_path = tmp_path / "arsenal_data.db"
    _make_db(str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE players SET profile_json = '{}' WHERE group_id = ? AND user_id = ?", ("g1", "u1"))
    conn.execute("INSERT INTO profile_updates VALUES (?, ?, ?, ?, ?, ?)", ("u1", "g1", "{}", json.dumps({"personality": "最新画像"}, ensure_ascii=False), "trigger", "2026-05-23 12:00:00"))
    conn.commit()
    conn.close()

    detail = SQLiteService(str(db_path)).get_user_detail("g1", "u1")

    assert detail["personality_profile"] == {"personality": "最新画像"}


def test_group_password_is_hashed_and_verified(tmp_path):
    db_path = tmp_path / "arsenal_data.db"
    _make_db(str(db_path))
    service = SQLiteService(str(db_path))

    settings = service.set_group_password("g1", "team-secret")

    assert settings == {"group_id": "g1", "memory_password_enabled": True}
    assert service.group_requires_password("g1") is True
    assert service.verify_group_password("g1", "team-secret") is True
    assert service.verify_group_password("g1", "wrong") is False
    groups = service.list_groups()
    assert groups[0]["memory_password_enabled"] is True

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT password_salt, password_hash FROM dashboard_group_settings WHERE group_id = ?", ("g1",)).fetchone()
    conn.close()
    assert row[0]
    assert row[1]
    assert "team-secret" not in row[0]
    assert "team-secret" not in row[1]


def test_clear_group_password_disables_protection(tmp_path):
    db_path = tmp_path / "arsenal_data.db"
    _make_db(str(db_path))
    service = SQLiteService(str(db_path))
    service.set_group_password("g1", "team-secret")

    settings = service.clear_group_password("g1")

    assert settings == {"group_id": "g1", "memory_password_enabled": False}
    assert service.group_requires_password("g1") is False
    assert service.verify_group_password("g1", "team-secret") is False
