import asyncio

import bot as bot_entry
from plugins.arteta_vision import VisionConfig, analyze_image_base64


def test_vision_config_never_uses_image_generation_credentials():
    config = VisionConfig(vision_api_key="", vision_api_url="")

    assert config.configured_api_key() == ""
    assert config.configured_api_url() == ""
    assert not hasattr(config, "image_api_key")
    assert not hasattr(config, "image_api_url")


def test_analyze_image_uses_configured_vision_service_before_siliconflow(monkeypatch):
    calls = []

    async def fake_call(api_url, api_key, model, data_url, timeout=30.0):
        calls.append((api_url, api_key, model, timeout))
        return "configured result"

    monkeypatch.setattr("plugins.arteta_vision._normalize_image_data_url", lambda value: value)
    monkeypatch.setattr("plugins.arteta_vision._call_vision_api", fake_call)

    result = asyncio.run(
        analyze_image_base64(
            "data:image/jpeg;base64,abc",
            VisionConfig(
                vision_api_key="sk-configured",
                vision_api_url="https://configured.example.com/v1",
                vision_model="qwen3.7-plus",
                siliconflow_api_key="sk-silicon",
                siliconflow_model="Qwen/Qwen3-VL-32B-Instruct",
                vision_timeout=75.0,
            ),
        )
    )

    assert result == "configured result"
    assert calls == [("https://configured.example.com/v1", "sk-configured", "qwen3.7-plus", 75.0)]


def test_analyze_image_falls_back_to_siliconflow_after_configured_service_fails(monkeypatch):
    calls = []

    async def fake_call(api_url, api_key, model, data_url, timeout=30.0):
        calls.append((api_url, api_key, model, timeout))
        if api_url == "https://configured.example.com/v1":
            return "[图片识别失败：HTTP 500 body=bad]"
        return "silicon result"

    monkeypatch.setattr("plugins.arteta_vision._normalize_image_data_url", lambda value: value)
    monkeypatch.setattr("plugins.arteta_vision._call_vision_api", fake_call)

    result = asyncio.run(
        analyze_image_base64(
            "data:image/jpeg;base64,abc",
            VisionConfig(
                vision_api_key="sk-configured",
                vision_api_url="https://configured.example.com/v1",
                vision_model="qwen3.7-plus",
                siliconflow_api_key="sk-silicon",
                siliconflow_model="Qwen/Qwen3-VL-32B-Instruct",
                vision_timeout=60.0,
            ),
        )
    )

    assert result == "silicon result"
    assert calls == [
        ("https://configured.example.com/v1", "sk-configured", "qwen3.7-plus", 60.0),
        ("https://api.siliconflow.cn", "sk-silicon", "Qwen/Qwen3-VL-32B-Instruct", 60.0),
    ]


def test_sanitize_log_message_masks_loaded_config_secrets():
    message = (
        "Loaded Config: {'deepseek_api_key': 'sk-secret-value', "
        "'vision_api_key': 'sk-vision-value', 'dashboard_secret_key': 'abc123', "
        "'vision_model': 'qwen3.7-plus'}"
    )

    sanitized = bot_entry.sanitize_log_message(message)

    assert "sk-secret-value" not in sanitized
    assert "sk-vision-value" not in sanitized
    assert "abc123" not in sanitized
    assert "'vision_model': 'qwen3.7-plus'" in sanitized


def test_loguru_filter_masks_record_message():
    record = {"message": "'deepseek_api_key': 'sk-secret-value', 'vision_model': 'qwen3.7-plus'"}

    assert bot_entry._sanitize_loguru_filter(record) is True
    assert "sk-secret-value" not in record["message"]
    assert "'vision_model': 'qwen3.7-plus'" in record["message"]
