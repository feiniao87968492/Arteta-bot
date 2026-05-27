import asyncio
import importlib.util
import pathlib
from typing import Dict, Tuple

from plugins.arteta_vision import (
    _build_vision_api_request,
    _extract_vision_api_response,
)


def _load_chat_trigger_helpers():
    source = pathlib.Path("plugins/arteta_chat.py").read_text(encoding="utf-8")
    start = source.index("def _segment_mentions_bot")
    end = source.index("# --- 2. 指令定义区 ---")
    namespace = {}
    exec(source[start:end], namespace)
    return namespace


def _select_vision_api_key(vision_api_key: str, image_api_key: str) -> str:
    return vision_api_key or image_api_key


def _select_vision_api_url(vision_api_url: str, image_api_url: str) -> str:
    return vision_api_url or image_api_url


class FakeEvent:
    def __init__(self, message, original_message=None, to_me=False, self_id="3443862126"):
        self.message = message
        self.original_message = original_message if original_message is not None else message
        self.to_me = to_me
        self.self_id = self_id

    def is_tome(self):
        return self.to_me

    def get_message(self):
        return self.message


class FakeSegment:
    def __init__(self, type_, data):
        self.type = type_
        self.data = data


def test_message_mentions_bot_uses_original_message_after_reply_preprocessing():
    helper = _load_chat_trigger_helpers()["_message_mentions_bot"]
    event = FakeEvent(
        message=[FakeSegment("text", {"text": "这张图讲了什么"})],
        original_message=[
            FakeSegment("reply", {"id": "1063516820"}),
            FakeSegment("at", {"qq": "3443862126"}),
            FakeSegment("text", {"text": " 这张图讲了什么"}),
        ],
        to_me=False,
    )

    assert asyncio.run(helper(event)) is True


def test_message_mentions_bot_ignores_middle_mentions():
    helper = _load_chat_trigger_helpers()["_message_mentions_bot"]
    event = FakeEvent(
        message=[FakeSegment("text", {"text": "你觉得"}), FakeSegment("at", {"qq": "3443862126"}), FakeSegment("text", {"text": "咋样"})],
        to_me=False,
    )

    assert asyncio.run(helper(event)) is False


def test_select_vision_api_key_prefers_dedicated_key():
    assert _select_vision_api_key("sk-vision", "sk-image") == "sk-vision"


def test_select_vision_api_key_falls_back_to_image_key():
    assert _select_vision_api_key("", "sk-image") == "sk-image"


def test_select_vision_api_url_prefers_dedicated_url():
    assert _select_vision_api_url("https://vision.example.com/anthropic", "https://image.example.com") == "https://vision.example.com/anthropic"


def test_select_vision_api_url_falls_back_to_image_url():
    assert _select_vision_api_url("", "https://image.example.com") == "https://image.example.com"


def test_build_vision_request_uses_anthropic_messages_for_anthropic_url():
    url, headers, payload = _build_vision_api_request(
        "https://token-plan-cn.xiaomimimo.com/anthropic",
        "sk-vision",
        "mimo-v2.5-pro",
        "data:image/png;base64,abc123",
    )

    assert url == "https://token-plan-cn.xiaomimimo.com/anthropic/v1/messages"
    assert headers["x-api-key"] == "sk-vision"
    assert headers["anthropic-version"] == "2023-06-01"
    assert payload["model"] == "mimo-v2.5-pro"
    image = payload["messages"][0]["content"][0]
    assert image == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "abc123"},
    }


def test_build_vision_request_keeps_openai_chat_completions_for_regular_url():
    url, headers, payload = _build_vision_api_request(
        "https://api.duckcoding.ai",
        "sk-image",
        "gpt-4o-mini",
        "data:image/jpeg;base64,def456",
    )

    assert url == "https://api.duckcoding.ai/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-image"
    assert payload["messages"][0]["content"][0] == {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,def456"},
    }


def test_build_vision_request_does_not_duplicate_openai_v1_path():
    url, headers, payload = _build_vision_api_request(
        "https://api.xiaomimimo.com/v1",
        "sk-image",
        "mimo-v2.5-pro",
        "data:image/png;base64,abc123",
    )

    assert url == "https://api.xiaomimimo.com/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-image"
    assert payload["model"] == "mimo-v2.5-pro"


def test_build_vision_request_uses_xiaomi_completion_token_parameter():
    url, headers, payload = _build_vision_api_request(
        "https://api.xiaomimimo.com/v1",
        "sk-image",
        "mimo-v2.5",
        "data:image/png;base64,abc123",
    )

    assert url == "https://api.xiaomimimo.com/v1/chat/completions"
    assert payload["max_completion_tokens"] == 1024
    assert "max_tokens" not in payload
    assert payload["messages"][0] == {
        "role": "system",
        "content": "You are MiMo, an AI assistant developed by Xiaomi.",
    }


def test_extract_vision_response_reads_anthropic_text_blocks():
    result = _extract_vision_api_response(
        "https://token-plan-cn.xiaomimimo.com/anthropic",
        {"content": [{"type": "text", "text": "这是一张测试图。"}]},
    )

    assert result == "这是一张测试图。"


def test_extract_vision_response_uses_reasoning_content_when_xiaomi_content_is_empty():
    result = _extract_vision_api_response(
        "https://api.xiaomimimo.com/v1",
        {"choices": [{"message": {"content": "", "reasoning_content": "这是一张截图。"}}]},
    )

    assert result == "这是一张截图。"
