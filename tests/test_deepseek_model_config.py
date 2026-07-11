from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = [
    "plugins/arteta_chat.py",
    "plugins/arteta_tools.py",
    "plugins/arteta_daily.py",
    "plugins/arteta_weekly.py",
    "plugins/arteta_standings.py",
    "plugins/arteta_agent/planner.py",
    "plugins/arteta_agent/activation.py",
]


def _read(rel_path):
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_runtime_files_do_not_hardcode_deepseek_flash():
    for rel_path in RUNTIME_FILES:
        text = _read(rel_path)
        assert '"model": "deepseek-v4-flash"' not in text, rel_path
        assert "https://api.deepseek.com/v1/chat/completions" not in text, rel_path


def test_chat_registers_tools_with_deepseek_model():
    text = _read("plugins/arteta_chat.py")
    assert "deepseek_model=DEEPSEEK_MODEL" in text


def test_chat_reads_configurable_deepseek_api_url():
    text = _read("plugins/arteta_chat.py")
    assert 'DEEPSEEK_API_URL = str(config.get("deepseek_api_url"' in text
    assert "DEEPSEEK_API_URL," in text


def test_agent_runtime_uses_configured_deepseek_api_url():
    chat_text = _read("plugins/arteta_chat.py")
    planner_text = _read("plugins/arteta_agent/planner.py")
    activation_text = _read("plugins/arteta_agent/activation.py")

    assert "api_url=DEEPSEEK_API_URL" in chat_text
    assert "run_agent_loop(" in chat_text
    assert "DEEPSEEK_MODEL" in chat_text
    assert "DEEPSEEK_API_KEY" in chat_text
    assert "DEEPSEEK_API_URL" in chat_text
    assert "api_url: str" in planner_text
    assert "api_url: str" in activation_text


def test_standings_plugin_is_deprecated_without_command_registration():
    text = _read("plugins/arteta_standings.py")

    assert "on_command" not in text
    assert "DEPRECATED" in text


def test_daily_plugin_imports_os_for_env_fallback():
    text = _read("plugins/arteta_daily.py")

    assert "import os" in text


def test_deploy_files_expose_deepseek_model_default():
    deploy_text = _read("deploy/deploy_ecs.sh")
    env_dev_text = _read(".env.dev")

    assert 'DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-gpt-5.5}"' in deploy_text
    assert 'DEEPSEEK_TEMPERATURE="${DEEPSEEK_TEMPERATURE:-0.9}"' in deploy_text
    assert "DEEPSEEK_MODEL=${DEEPSEEK_MODEL}" in deploy_text
    assert "DEEPSEEK_TEMPERATURE=${DEEPSEEK_TEMPERATURE}" in deploy_text
    assert "DEEPSEEK_MODEL=gpt-5.5" in env_dev_text
    assert "DEEPSEEK_TEMPERATURE=0.9" in env_dev_text


def test_env_dev_keeps_secret_values_blank():
    env_dev_text = _read(".env.dev")

    assert "DEEPSEEK_API_KEY=\n" in env_dev_text
    assert "IMAGE_API_KEY=\n" in env_dev_text
    assert "VISION_API_KEY=\n" in env_dev_text
    assert "sk-" not in env_dev_text
