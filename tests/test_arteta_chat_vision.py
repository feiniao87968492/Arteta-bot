import asyncio
import importlib.util
import pathlib
import types
from typing import Dict, Tuple

from plugins.arteta_vision import (
    _build_vision_api_request,
    _extract_vision_api_response,
)


def _load_chat_trigger_helpers():
    source = pathlib.Path("plugins/arteta_chat.py").read_text(encoding="utf-8")
    start = source.index("def _segment_mentions_bot")
    end = source.index("# --- 2. 指令定义区 ---")
    from plugins.arteta_agent.activation import is_activation_candidate

    namespace = {
        "USE_AGENT_REGISTRY": True,
        "AGENT_AUTONOMOUS_ACTIVATION": True,
        "AGENT_ACTIVATION_TIMEOUT": 4.0,
        "DEEPSEEK_MODEL": "model",
        "DEEPSEEK_API_KEY": "key",
        "DEEPSEEK_API_URL": "https://api.example/v1/chat/completions",
        "re": __import__("re"),
        "is_activation_candidate": is_activation_candidate,
        "decide_activation_with_agent": None,
    }
    exec(source[start:end], namespace)
    return namespace


def _load_fetch_quoted_chain_helper():
    source = pathlib.Path("plugins/arteta_chat.py").read_text(encoding="utf-8")
    helper_start = source.index("_URL_RE =")
    helper_end = source.index("def _segment_mentions_bot")
    fetch_start = source.index("async def fetch_quoted_chain")
    end = source.index("# --- 7. 核心引擎与路由 ---")
    namespace = {
        "asyncio": asyncio,
        "json": __import__("json"),
        "os": __import__("os"),
        "re": __import__("re"),
        "urlparse": __import__("urllib.parse").parse.urlparse,
        "Optional": __import__("typing").Optional,
        "Path": pathlib.Path,
        "analyze_image": None,
        "Bot": object,
    }
    exec(source[helper_start:helper_end] + "\n" + source[fetch_start:end], namespace)
    return namespace


def _select_vision_api_key(vision_api_key: str, image_api_key: str) -> str:
    return vision_api_key or image_api_key


def _select_vision_api_url(vision_api_url: str, image_api_url: str) -> str:
    return vision_api_url or image_api_url


class FakeEvent:
    def __init__(self, message, original_message=None, to_me=False, self_id="3443862126", group_id="543915926"):
        self.message = FakeMessage(message)
        self.original_message = FakeMessage(original_message) if original_message is not None else self.message
        self.to_me = to_me
        self.self_id = self_id
        self.group_id = group_id

    def is_tome(self):
        return self.to_me

    def get_message(self):
        return self.message


class FakeMessage(list):
    def extract_plain_text(self):
        return "".join(str(seg.data.get("text", "")) for seg in self if seg.type == "text")


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


def test_agent_activation_prefilter_accepts_images_questions_and_domain_intents():
    helper = _load_chat_trigger_helpers()["should_consider_agent_response"]

    assert helper(FakeEvent([FakeSegment("image", {"url": "https://img.example/a.png"})]), raw_text="这张图讲了什么") is True
    assert helper(FakeEvent([FakeSegment("text", {"text": "塔子 最近阿森纳怎么样"})]), raw_text="塔子 最近阿森纳怎么样") is True
    assert helper(FakeEvent([FakeSegment("text", {"text": "A leetcode 两数之和"})]), raw_text="A leetcode 两数之和") is True
    assert helper(FakeEvent([FakeSegment("text", {"text": "A 查一下积分榜"})]), raw_text="A 查一下积分榜") is True


def test_agent_activation_prefilter_accepts_explicit_pending_confirmation():
    helper = _load_chat_trigger_helpers()["should_consider_agent_response"]
    action_id = "0123456789abcdef0123456789abcdef"

    assert helper(
        FakeEvent([FakeSegment("text", {"text": "确认 {0}".format(action_id)})]),
        raw_text="确认 {0}".format(action_id),
    ) is True
    assert helper(
        FakeEvent([FakeSegment("text", {"text": "confirm {0}".format(action_id)})]),
        raw_text="confirm {0}".format(action_id),
    ) is True


def test_agent_activation_prefilter_rejects_plain_group_chatter():
    helper = _load_chat_trigger_helpers()["should_consider_agent_response"]

    assert helper(FakeEvent([FakeSegment("text", {"text": "今晚吃什么"})]), raw_text="今晚吃什么") is False
    assert helper(FakeEvent([FakeSegment("text", {"text": "皇马准备以创纪录价格求购奥利塞，转会费很高"})]), raw_text="皇马准备以创纪录价格求购奥利塞，转会费很高") is False


def test_agent_activation_prefilter_rejects_image_without_request_text():
    helper = _load_chat_trigger_helpers()["should_consider_agent_response"]

    assert helper(FakeEvent([FakeSegment("image", {"url": "https://img.example/a.png"})]), raw_text="") is False


def test_message_should_trigger_agent_uses_activation_judge_for_candidate():
    namespace = _load_chat_trigger_helpers()
    calls = []

    async def fake_decide(raw_text, has_image, group_id, model, api_key, api_url="", timeout=0):
        calls.append((raw_text, has_image, group_id, model, api_key, api_url, timeout))
        return types.SimpleNamespace(should_reply=True, reason="task-like Arsenal question")

    namespace["decide_activation_with_agent"] = fake_decide
    event = FakeEvent(
        [FakeSegment("text", {"text": "\u6700\u8fd1\u963f\u68ee\u7eb3\u600e\u4e48\u6837"})],
        group_id="1104602373",
    )

    assert asyncio.run(namespace["_message_should_trigger_agent"](event)) is True
    assert calls == [("\u6700\u8fd1\u963f\u68ee\u7eb3\u600e\u4e48\u6837", False, "1104602373", "model", "key", "https://api.example/v1/chat/completions", 4.0)]


def test_message_should_trigger_agent_does_not_judge_plain_chatter():
    namespace = _load_chat_trigger_helpers()

    async def broken_decide(*args, **kwargs):
        raise AssertionError("activation judge should not run for ordinary chatter")

    namespace["decide_activation_with_agent"] = broken_decide
    event = FakeEvent([FakeSegment("text", {"text": "\u7f57\u54e5\u7684\u6bd4\u8d5b\u662f\u4e03\u70b9"})])

    assert asyncio.run(namespace["_message_should_trigger_agent"](event)) is False


def test_fetch_quoted_chain_collects_image_urls_without_analyzing_in_agent_mode():
    pathlib.Path("/tmp").mkdir(exist_ok=True)
    namespace = _load_fetch_quoted_chain_helper()
    calls = []

    async def fake_analyze_image(url):
        calls.append(url)
        return "should-not-run"

    namespace["analyze_image"] = fake_analyze_image

    class FakeBot:
        async def get_msg(self, message_id):
            return {
                "sender": {"card": "Tester", "user_id": "u1"},
                "message": [{"type": "image", "data": {"file": "f1", "url": "https://old.example/a.png"}}],
            }

        async def get_image(self, file):
            return {"url": "https://fresh.example/a.png"}

    image_urls = []
    text = asyncio.run(namespace["fetch_quoted_chain"](FakeBot(), 123, image_urls=image_urls, analyze_images=False))

    assert image_urls == ["https://fresh.example/a.png"]
    assert "可调用 analyze_image" in text
    assert calls == []


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
