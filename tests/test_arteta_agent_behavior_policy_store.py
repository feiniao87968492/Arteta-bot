import json


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
