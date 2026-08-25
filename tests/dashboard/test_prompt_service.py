import json

import pytest

from dashboard.api.services.prompt_service import PromptService, get_prompt


def test_missing_registry_returns_builtin_defaults(tmp_path):
    service = PromptService(str(tmp_path / "missing.json"))

    entries = service.list_entries()

    keys = {entry["key"] for entry in entries}
    assert "arteta.main" in keys
    assert "daily.summary" in keys
    assert next(entry for entry in entries if entry["key"] == "arteta.main")["builtin"] is True


def test_registry_override_is_returned(tmp_path):
    registry = tmp_path / "prompts.json"
    registry.write_text(json.dumps({
        "version": 1,
        "entries": [{
            "key": "arteta.main",
            "title": "主对话人设",
            "category": "主对话",
            "content": "新的塔子人设",
            "variables": [],
            "enabled": True,
            "builtin": True,
        }],
    }, ensure_ascii=False), encoding="utf-8")

    service = PromptService(str(registry))

    assert service.get_prompt("arteta.main", "默认人设") == "新的塔子人设"


def test_disabled_builtin_falls_back_to_default(tmp_path):
    registry = tmp_path / "prompts.json"
    registry.write_text(json.dumps({
        "version": 1,
        "entries": [{
            "key": "arteta.main",
            "title": "主对话人设",
            "category": "主对话",
            "content": "禁用内容",
            "variables": [],
            "enabled": False,
            "builtin": True,
        }],
    }, ensure_ascii=False), encoding="utf-8")

    service = PromptService(str(registry))

    assert service.get_prompt("arteta.main", "默认人设") == "默认人设"


def test_create_update_delete_user_entry(tmp_path):
    service = PromptService(str(tmp_path / "prompts.json"))

    created = service.create_entry({
        "key": "custom.touchline",
        "title": "边线提醒",
        "category": "自定义",
        "content": "压上去！",
        "variables": [],
        "enabled": True,
    })
    assert created["builtin"] is False

    updated = service.update_entry("custom.touchline", {"content": "稳住阵型。", "enabled": True})
    assert updated["content"] == "稳住阵型。"

    service.delete_entry("custom.touchline")
    assert all(entry["key"] != "custom.touchline" for entry in service.list_entries())


def test_builtin_delete_is_rejected(tmp_path):
    service = PromptService(str(tmp_path / "prompts.json"))

    with pytest.raises(ValueError) as exc:
        service.delete_entry("arteta.main")

    assert "built-in" in str(exc.value)


def test_invalid_json_returns_defaults(tmp_path):
    registry = tmp_path / "prompts.json"
    registry.write_text("{ broken", encoding="utf-8")

    service = PromptService(str(registry))

    assert service.get_prompt("arteta.main", "默认人设") == "默认人设"
    assert any(entry["key"] == "arteta.main" for entry in service.list_entries())


def test_required_variable_validation(tmp_path):
    service = PromptService(str(tmp_path / "prompts.json"))
    service.update_entry("weekly.report", {"content": "新闻：{missing}", "enabled": True})

    assert service.get_prompt("weekly.report", "新闻：{articles}", variables={"articles": "A"}) == "新闻：A"


def test_module_get_prompt_uses_environment_path(monkeypatch, tmp_path):
    registry = tmp_path / "prompts.json"
    registry.write_text(json.dumps({
        "version": 1,
        "entries": [{
            "key": "arteta.main",
            "title": "主对话人设",
            "category": "主对话",
            "content": "环境覆盖",
            "variables": [],
            "enabled": True,
            "builtin": True,
        }],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("ARTETA_PROMPTS_FILE", str(registry))

    assert get_prompt("arteta.main", "默认") == "环境覆盖"


def test_get_prompt_formats_valid_override(tmp_path):
    service = PromptService(str(tmp_path / "prompts.json"))
    service.update_entry("weekly.report", {"content": "本周：{articles}", "enabled": True})

    assert service.get_prompt("weekly.report", "默认：{articles}", variables={"articles": "新闻"}) == "本周：新闻"


def test_default_config_prompts_json_is_valid():
    service = PromptService("config/prompts.json")

    keys = {entry["key"] for entry in service.list_entries()}

    assert "arteta.main" in keys
    assert "algo.coach" in keys


def test_list_entries_exposes_builtin_default_content_when_registry_blank(tmp_path):
    registry = tmp_path / "prompts.json"
    registry.write_text(json.dumps({
        "version": 1,
        "entries": [{
            "key": "arteta.main",
            "title": "主对话人设",
            "category": "主对话",
            "content": "",
            "variables": [],
            "enabled": False,
            "builtin": True,
        }],
    }, ensure_ascii=False), encoding="utf-8")
    service = PromptService(str(registry))

    entries = service.list_entries()
    arteta_entry = next(entry for entry in entries if entry["key"] == "arteta.main")
    algo_entry = next(entry for entry in entries if entry["key"] == "algo.coach")

    assert "阿森纳主帅" in arteta_entry["content"]
    assert "技术指导" in algo_entry["content"]


def test_get_prompt_respects_caller_default_even_when_builtin_default_exists(tmp_path):
    service = PromptService(str(tmp_path / "missing.json"))

    # 没有 registry 覆盖时，调用方传入的 default 优先于 service 内置默认 content，
    # 避免运行时与代码常量漂移
    assert service.get_prompt("arteta.main", "调用方默认人设") == "调用方默认人设"
