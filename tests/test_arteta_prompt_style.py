from pathlib import Path
import json

from dashboard.api.services.prompt_service import PromptService
from plugins.arteta_agent import prompts


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path):
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_arteta_prompt_defaults_are_centralized():
    from plugins import arteta_chat
    from dashboard.api.services import bot_chat_service
    from dashboard.api.services import prompt_service

    assert hasattr(prompts, "ARTETA_PERSONA_CORE")
    assert hasattr(prompts, "ARTETA_RESPONSE_RULES")
    assert arteta_chat.ARTETA_PROMPT == prompts.ARTETA_DEFAULT_PROMPT
    assert bot_chat_service.ARTETA_PROMPT == prompts.ARTETA_DEFAULT_PROMPT

    default_entries = {
        entry["key"]: entry
        for entry in prompt_service.DEFAULT_PROMPTS
    }
    assert default_entries["arteta.main"]["content"] == prompts.ARTETA_DEFAULT_PROMPT
    assert default_entries["arteta.dashboard_chat"]["content"] == prompts.ARTETA_DEFAULT_PROMPT


def test_arteta_default_prompt_blocks_fixed_actions_and_favor_marker_dead_command():
    prompt = prompts.ARTETA_DEFAULT_PROMPT
    fixed_table_action = "拍" + "桌子"

    forbidden = [
        "可以先" + fixed_table_action,
        fixed_table_action,
        "敲" + "战术板",
        "推开" + "更衣室门",
        "第一句" + "就要有劲",
        "默认用 " + "2-4 个自然段",
        "无论对方问什么，都要先正面、详细地回答",
        "信任度评估——死命令",
        "你的回复正文结束后" + "必须另起一行",
        "【好感度+++】",
    ]
    for marker in forbidden:
        assert marker not in prompt

    assert "开场直接表达态度" in prompt
    assert "不要描述自己的肢体动作" in prompt
    assert "简单问题可以只回答 1～3 句" in prompt
    assert "梗图先接梗" in prompt
    assert "新闻回答先区分已确认事实、传闻和个人判断" in prompt


def test_current_turn_style_guard_does_not_reintroduce_fixed_action_template():
    from plugins import arteta_chat

    messages = [{"role": "system", "content": "BASE"}]

    arteta_chat.append_current_turn_style_guard(messages)

    content = messages[-1]["content"]
    assert "第一句" + "就要有劲" not in content
    assert "可以先" + "拍桌子" not in content
    assert "拍" + "桌子" not in content
    assert "不要描述自己的肢体动作" in content
    assert "简单问题可以只回答 1～3 句" in content


def test_enabled_prompt_registry_override_with_stale_fixed_action_rules_is_ignored(tmp_path):
    registry = tmp_path / "prompts.json"
    registry.write_text(json.dumps({
        "version": 1,
        "entries": [{
            "key": "arteta.main",
            "title": "主对话人设",
            "category": "主对话",
            "content": "旧的人设：{0}，{1}。".format(
                "第一句" + "就要有劲",
                "可以先" + "拍桌子",
            ),
            "variables": [],
            "enabled": True,
            "builtin": True,
        }],
    }, ensure_ascii=False), encoding="utf-8")

    prompt = PromptService(str(registry)).get_prompt(
        "arteta.main",
        prompts.ARTETA_DEFAULT_PROMPT,
    )

    assert "第一句" + "就要有劲" not in prompt
    assert "可以先" + "拍桌子" not in prompt
    assert prompt == prompts.ARTETA_DEFAULT_PROMPT
