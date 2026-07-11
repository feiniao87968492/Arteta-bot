from dashboard.api.services.env_service import EnvService


def test_mask_and_update_whitelisted_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY=sk-abcdef123456\nOTHER=value\n", encoding="utf-8")
    service = EnvService(str(env_file), ["DEEPSEEK_API_KEY"])
    values = service.list_masked()
    assert values[0]["name"] == "DEEPSEEK_API_KEY"
    assert values[0]["exists"] is True
    assert values[0]["masked"].startswith("sk-")
    assert "abcdef" not in values[0]["masked"]

    service.update("DEEPSEEK_API_KEY", "sk-newvalue9999")
    text = env_file.read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=sk-newvalue9999" in text
    assert "OTHER=value" in text


def test_update_syncs_dashboard_runtime_environment(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_MODEL=old-model\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    service = EnvService(str(env_file), ["DEEPSEEK_MODEL"])

    service.update("DEEPSEEK_MODEL", "deepseek-v4-flash")

    assert service.get("DEEPSEEK_MODEL") == "deepseek-v4-flash"
    assert service.check_effective("DEEPSEEK_MODEL")["effective"] is True
    assert service.check_effective("DEEPSEEK_MODEL")["runtime_value"] == "deepseek-v4-flash"


def test_model_and_url_values_are_not_masked(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ALGO_API_KEY=sk-secret123456\n"
        "ALGO_API_URL=https://www.boxying.com/v1/chat/completions\n"
        "ALGO_MODEL=gpt-5.5\n"
        "DEEPSEEK_MODEL=gpt-5.5\n"
        "IMAGE_BASE_URL=https://image.example.com/v1\n",
        encoding="utf-8",
    )
    service = EnvService(
        str(env_file),
        ["ALGO_API_KEY", "ALGO_API_URL", "ALGO_MODEL", "DEEPSEEK_MODEL", "IMAGE_BASE_URL"],
    )

    values = {item["name"]: item for item in service.list_masked()}

    assert values["ALGO_API_KEY"]["masked"] != "sk-secret123456"
    assert values["ALGO_API_URL"]["masked"] == "https://www.boxying.com/v1/chat/completions"
    assert values["ALGO_MODEL"]["masked"] == "gpt-5.5"
    assert values["DEEPSEEK_MODEL"]["masked"] == "gpt-5.5"
    assert values["IMAGE_BASE_URL"]["masked"] == "https://image.example.com/v1"
