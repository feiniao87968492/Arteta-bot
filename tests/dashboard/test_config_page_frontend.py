from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _source() -> str:
    return (ROOT / "dashboard/web/src/pages/ConfigPage.tsx").read_text(encoding="utf-8")


def test_config_page_renders_grouped_provider_fields_and_secret_inputs():
    source = _source()

    assert "type={field.secret ? 'password' : 'text'}" in source
    assert "/api/config/providers" in source
    assert "provider.fields" in source


def test_config_page_requires_verify_before_apply():
    source = _source()

    assert "/validate" in source
    assert "/apply" in source
    assert "validation[provider.id]" in source
    assert "setValidation(current => ({ ...current, [provider.id]: null }))" in source


def test_config_page_has_no_global_restart_action():
    source = _source()

    assert "/api/config/restart-bot" not in source
    assert "Apply and restart bot" in source
