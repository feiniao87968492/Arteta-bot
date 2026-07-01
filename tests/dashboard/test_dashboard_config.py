import pytest

from dashboard.api.config import ENV_WHITELIST, get_settings, validate_public_settings


def test_dashboard_settings_include_logs_web_dist_and_public(monkeypatch, tmp_path):
    logs_dir = tmp_path / "ecs_logs"
    web_dist = tmp_path / "dist"
    env_file = tmp_path / ".env"

    monkeypatch.setenv("DASHBOARD_LOGS_DIR", str(logs_dir))
    monkeypatch.setenv("DASHBOARD_WEB_DIST", str(web_dist))
    monkeypatch.setenv("DASHBOARD_ENV_FILE", str(env_file))
    monkeypatch.setenv("DASHBOARD_PUBLIC", "true")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "strong-secret")

    settings = get_settings()

    assert settings.logs_dir == str(logs_dir)
    assert settings.web_dist == str(web_dist)
    assert settings.env_file == str(env_file)
    assert settings.public is True


def test_dashboard_config_whitelist_includes_vision_api_key():
    assert "VISION_API_KEY" in ENV_WHITELIST
    assert "VISION_API_URL" in ENV_WHITELIST
    assert "VISION_MODEL" in ENV_WHITELIST
    assert "VISION_TIMEOUT" in ENV_WHITELIST


def test_dashboard_config_whitelist_includes_deepseek_model():
    assert "DEEPSEEK_MODEL" in ENV_WHITELIST


def test_validate_public_settings_rejects_missing_secret(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PUBLIC", "true")
    monkeypatch.delenv("DASHBOARD_SECRET_KEY", raising=False)

    settings = get_settings()

    with pytest.raises(RuntimeError) as exc:
        validate_public_settings(settings)
    assert "DASHBOARD_SECRET_KEY" in str(exc.value)


def test_validate_public_settings_allows_local_dev_without_secret(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PUBLIC", "false")
    monkeypatch.delenv("DASHBOARD_SECRET_KEY", raising=False)

    settings = get_settings()

    validate_public_settings(settings)


def test_dashboard_settings_include_prompts_file(monkeypatch, tmp_path):
    prompts_file = tmp_path / "prompts.json"

    monkeypatch.setenv("ARTETA_PROMPTS_FILE", str(prompts_file))

    settings = get_settings()

    assert settings.prompts_file == str(prompts_file)
