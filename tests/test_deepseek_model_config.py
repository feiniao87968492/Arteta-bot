from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = [
    "plugins/arteta_chat.py",
    "plugins/arteta_tools.py",
    "plugins/arteta_daily.py",
    "plugins/arteta_weekly.py",
    "plugins/arteta_standings.py",
]


def _read(rel_path):
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_runtime_files_do_not_hardcode_deepseek_flash():
    for rel_path in RUNTIME_FILES:
        text = _read(rel_path)
        assert '"model": "deepseek-v4-flash"' not in text, rel_path


def test_chat_registers_tools_with_deepseek_model():
    text = _read("plugins/arteta_chat.py")
    assert "deepseek_model=DEEPSEEK_MODEL" in text


def test_deploy_files_expose_deepseek_model_default():
    deploy_text = _read("deploy/deploy_ecs.sh")

    assert 'DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-pro}"' in deploy_text
    assert "DEEPSEEK_MODEL=${DEEPSEEK_MODEL}" in deploy_text
