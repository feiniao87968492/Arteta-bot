from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _source() -> str:
    return (ROOT / "dashboard/web/src/pages/ConfigPage.tsx").read_text(encoding="utf-8")


def test_config_page_masks_secret_inputs_for_editing_values():
    source = _source()

    assert 'type="password"' in source


def test_config_page_exposes_effective_config_test_action():
    source = _source()

    assert "/api/config/keys/" in source
    assert "/test" in source
    assert "Dashboard API 已生效" in source


def test_config_page_exposes_bot_restart_action():
    source = _source()

    assert "/api/config/restart-bot" in source
    assert "重启 QQ Bot" in source
    assert "重启后会重新读取配置文件" in source
