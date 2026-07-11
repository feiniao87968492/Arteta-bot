import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor


def test_behavior_policy_migrates_legacy_json_to_sqlite_and_keeps_backup(tmp_path, monkeypatch):
    from plugins.arteta_agent import behavior_policy

    json_path = tmp_path / "agent_behavior_policy.json"
    db_path = tmp_path / "agent_behavior_policy.db"
    json_path.write_text(json.dumps({
        "groups": {
            "group-1": {
                "policies": {
                    "emoji.enabled": {
                        "key": "emoji.enabled",
                        "value": False,
                        "mode": "soft",
                        "reason": "legacy",
                        "source": "agent",
                        "ttl_turns": 2,
                    }
                },
                "phrase_styles": [
                    {"phrase": "重点", "color": "red"},
                ],
            }
        }
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("ARTETA_AGENT_BEHAVIOR_POLICY_PATH", str(json_path))
    monkeypatch.setenv("ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH", str(db_path))

    assert behavior_policy.get_group_policy("group-1", "emoji.enabled")["value"] is False
    assert behavior_policy.get_phrase_styles("group-1") == [{"phrase": "重点", "color": "red"}]
    assert db_path.exists()
    assert (tmp_path / "agent_behavior_policy.json.bak").exists()


def test_behavior_policy_sqlite_ttl_semantics_and_permanent_policy(tmp_path, monkeypatch):
    from plugins.arteta_agent import behavior_policy

    monkeypatch.setenv("ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH", str(tmp_path / "policy.db"))
    monkeypatch.delenv("ARTETA_AGENT_BEHAVIOR_POLICY_PATH", raising=False)
    monkeypatch.delenv("ARTETA_AGENT_UI_PREFS_PATH", raising=False)
    monkeypatch.delenv("ARTETA_AGENT_TOOL_POLICY_PATH", raising=False)

    temporary = behavior_policy.set_group_policy(
        "group-1",
        "emoji.enabled",
        False,
        ttl_turns=2,
        reason="temporary",
    )
    permanent = behavior_policy.set_group_policy(
        "group-1",
        "route.public_current_fact.preferred_tool",
        "grok_search",
        reason="permanent",
    )

    assert temporary["ttl_turns"] == 2
    assert "ttl_turns" not in permanent

    behavior_policy.consume_group_policy_turn("group-1")

    assert behavior_policy.get_group_policy("group-1", "emoji.enabled")["ttl_turns"] == 1
    assert behavior_policy.get_group_policy(
        "group-1",
        "route.public_current_fact.preferred_tool",
    )["value"] == "grok_search"

    behavior_policy.consume_group_policy_turn("group-1")

    assert behavior_policy.get_group_policy("group-1", "emoji.enabled") == {}
    assert behavior_policy.get_group_policy(
        "group-1",
        "route.public_current_fact.preferred_tool",
    )["value"] == "grok_search"


def test_behavior_policy_sqlite_does_not_remigrate_when_db_has_data(tmp_path, monkeypatch):
    from plugins.arteta_agent import behavior_policy

    json_path = tmp_path / "agent_behavior_policy.json"
    db_path = tmp_path / "agent_behavior_policy.db"
    monkeypatch.setenv("ARTETA_AGENT_BEHAVIOR_POLICY_PATH", str(json_path))
    monkeypatch.setenv("ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH", str(db_path))

    behavior_policy.set_group_policy("group-1", "emoji.enabled", True)
    json_path.write_text(json.dumps({
        "groups": {
            "group-1": {
                "policies": {
                    "emoji.enabled": {
                        "key": "emoji.enabled",
                        "value": False,
                        "mode": "soft",
                        "reason": "legacy",
                        "source": "agent",
                    }
                }
            }
        }
    }), encoding="utf-8")

    assert behavior_policy.get_group_policy("group-1", "emoji.enabled")["value"] is True
    assert not (tmp_path / "agent_behavior_policy.json.bak").exists()


def test_behavior_policy_sqlite_phrase_style_updates_do_not_lose_concurrent_fields(tmp_path, monkeypatch):
    from plugins.arteta_agent import behavior_policy

    db_path = tmp_path / "policy.db"
    monkeypatch.setenv("ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH", str(db_path))
    monkeypatch.delenv("ARTETA_AGENT_BEHAVIOR_POLICY_PATH", raising=False)
    monkeypatch.delenv("ARTETA_AGENT_UI_PREFS_PATH", raising=False)
    monkeypatch.delenv("ARTETA_AGENT_TOOL_POLICY_PATH", raising=False)

    behavior_policy.set_phrase_style("group-1", "focus", {"base": True})

    barrier = threading.Barrier(2)
    original_connect = behavior_policy._connect_sqlite
    select_count = [0]
    select_count_lock = threading.Lock()

    class DelayedSelectConnection(object):
        def __init__(self, inner):
            self.inner = inner

        def execute(self, sql, parameters=()):
            if (
                isinstance(sql, str)
                and "SELECT value_json FROM behavior_phrase_styles" in sql
            ):
                with select_count_lock:
                    select_count[0] += 1
                    should_wait = select_count[0] <= 2
                if should_wait:
                    try:
                        barrier.wait(timeout=1)
                    except threading.BrokenBarrierError:
                        pass
            return self.inner.execute(sql, parameters)

        def close(self):
            return self.inner.close()

    def delayed_connect():
        conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return DelayedSelectConnection(conn)

    monkeypatch.setattr(behavior_policy, "_connect_sqlite", delayed_connect)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(
            lambda item: behavior_policy.set_phrase_style("group-1", "focus", item),
            [{"color": "red"}, {"font_weight": 700}],
        ))

    monkeypatch.setattr(behavior_policy, "_connect_sqlite", original_connect)

    assert behavior_policy.get_phrase_styles("group-1") == [
        {
            "base": True,
            "color": "red",
            "font_weight": 700,
            "phrase": "focus",
        }
    ]


def test_behavior_policy_sqlite_concurrent_turn_consumes_are_atomic(tmp_path, monkeypatch):
    from plugins.arteta_agent import behavior_policy

    db_path = tmp_path / "policy.db"
    monkeypatch.setenv("ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH", str(db_path))
    monkeypatch.delenv("ARTETA_AGENT_BEHAVIOR_POLICY_PATH", raising=False)
    monkeypatch.delenv("ARTETA_AGENT_UI_PREFS_PATH", raising=False)
    monkeypatch.delenv("ARTETA_AGENT_TOOL_POLICY_PATH", raising=False)

    behavior_policy.set_group_policy("group-1", "emoji.enabled", False, ttl_turns=3)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: behavior_policy.consume_group_policy_turn("group-1"), range(2)))

    assert behavior_policy.get_group_policy("group-1", "emoji.enabled")["ttl_turns"] == 1
