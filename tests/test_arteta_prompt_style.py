from pathlib import Path
import json

from dashboard.api.services.prompt_service import PromptService


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path):
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_main_prompt_encourages_richer_warmer_replies():
    text = _read("plugins/arteta_chat.py")

    assert "控制要简短有力" not in text
    assert "有内容、有温度" in text
    assert "默认用 2-4 个自然段" in text
    assert "更衣室里的趣味" in text
    assert "第一句就要有劲" in text
    assert "语气要有起伏" in text
    assert "像群聊里活人接话" in text


def test_dashboard_prompt_default_does_not_force_brief_replies():
    text = _read("dashboard/api/services/prompt_service.py")
    default_region = text.split("DEFAULT_PROMPTS = [", 1)[0]

    assert "控制要简短有力" not in default_region
    assert "回答要简短有力" not in default_region
    assert "有内容、有温度" in default_region
    assert "默认用 2-4 个自然段" in default_region
    assert "第一句就要有劲" in default_region
    assert "语气要有起伏" in default_region


def test_enabled_prompt_registry_override_must_include_energy_rules(tmp_path):
    registry = tmp_path / "prompts.json"
    registry.write_text(json.dumps({
        "version": 1,
        "entries": [{
            "key": "arteta.main",
            "title": "主对话人设",
            "category": "主对话",
            "content": "旧的人设：控制要简短有力。",
            "variables": [],
            "enabled": True,
            "builtin": True,
        }],
    }, ensure_ascii=False), encoding="utf-8")

    prompt = PromptService(str(registry)).get_prompt(
        "arteta.main",
        "调用方默认：第一句就要有劲，语气要有起伏。",
    )

    assert "控制要简短有力" not in prompt
    assert "第一句就要有劲" in prompt
