import asyncio
from pathlib import Path

from plugins.arteta_agent.providers.http_client import (
    close_shared_async_client,
    get_shared_async_client,
    set_shared_async_client_factory,
)
from plugins.arteta_agent.providers.openai_compatible import OpenAICompatibleProvider


class FakeResponse:
    status_code = 200
    text = ""
    headers = {"content-type": "application/json"}

    def __init__(self, message):
        self.message = message

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": self.message}]}


class FakeClient:
    def __init__(self, calls, message):
        self.calls = calls
        self.message = message
        self.closed = False

    async def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, headers or {}, json or {}, timeout))
        return FakeResponse(self.message)

    async def aclose(self):
        self.closed = True


class FakeHTTPStatusError(Exception):
    def __init__(self, status_code):
        self.response = type("Response", (), {"status_code": status_code})()
        super().__init__("HTTP {0}".format(status_code))


class FailingStatusResponse:
    text = ""
    headers = {"content-type": "application/json"}

    def __init__(self, status_code):
        self.status_code = status_code

    def raise_for_status(self):
        raise FakeHTTPStatusError(self.status_code)

    def json(self):
        return {}


class SequenceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, headers or {}, json or {}, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_shared_async_client_is_reused_and_closed():
    created = []

    def factory():
        client = FakeClient([], {"role": "assistant", "content": "ok"})
        created.append(client)
        return client

    set_shared_async_client_factory(factory)
    try:
        first = get_shared_async_client()
        second = get_shared_async_client()

        assert first is second
        assert len(created) == 1

        asyncio.run(close_shared_async_client())

        assert first.closed is True
        third = get_shared_async_client()
        assert third is not first
        assert len(created) == 2
    finally:
        asyncio.run(close_shared_async_client())
        set_shared_async_client_factory(None)


def test_openai_compatible_provider_preserves_tool_calls_and_reasoning_content():
    calls = []
    client = FakeClient(
        calls,
        {
            "role": "assistant",
            "content": "answer",
            "reasoning_content": "thinking",
            "tool_calls": [{
                "id": "call-1",
                "function": {"name": "sample", "arguments": "{}"},
            }],
        },
    )
    provider = OpenAICompatibleProvider(client=client, api_url="https://provider.example/v1/chat/completions")

    result = asyncio.run(provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="model",
        api_key="key",
        tools=[{"type": "function", "function": {"name": "sample", "parameters": {"type": "object"}}}],
        temperature=0.2,
    ))

    assert result["role"] == "assistant"
    assert result["content"] == "answer"
    assert result["reasoning_content"] == "thinking"
    assert result["tool_calls"][0]["function"]["name"] == "sample"
    assert calls[0][0] == "https://provider.example/v1/chat/completions"
    assert calls[0][1]["Authorization"] == "Bearer key"
    assert calls[0][2]["temperature"] == 0.2
    assert calls[0][2]["tool_choice"] == "auto"
    assert calls[0][3] == 80.0


def test_openai_compatible_provider_merges_extra_payload_fields():
    calls = []
    client = FakeClient(calls, {"role": "assistant", "content": "{\"should_reply\": true}"})
    provider = OpenAICompatibleProvider(client=client, api_url="https://provider.example/v1/chat/completions")

    result = asyncio.run(provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="model",
        api_key="key",
        temperature=0,
        timeout=4.0,
        extra_payload={
            "max_tokens": 80,
            "response_format": {"type": "json_object"},
        },
    ))

    assert result["content"] == "{\"should_reply\": true}"
    assert calls[0][2]["temperature"] == 0
    assert calls[0][2]["max_tokens"] == 80
    assert calls[0][2]["response_format"] == {"type": "json_object"}
    assert calls[0][3] == 4.0


def test_openai_compatible_provider_retries_retryable_status_then_succeeds():
    client = SequenceClient([
        FailingStatusResponse(500),
        FakeResponse({"role": "assistant", "content": "ok after retry"}),
    ])
    provider = OpenAICompatibleProvider(
        client=client,
        api_url="https://provider.example/v1/chat/completions",
        max_retries=1,
        retry_backoff_seconds=0,
    )

    result = asyncio.run(provider.chat(
        messages=[{"role": "user", "content": "hi"}],
        model="model",
        api_key="key",
    ))

    assert result["content"] == "ok after retry"
    assert len(client.calls) == 2


def test_openai_compatible_provider_does_not_retry_non_retryable_status():
    client = SequenceClient([FailingStatusResponse(400)])
    provider = OpenAICompatibleProvider(
        client=client,
        api_url="https://provider.example/v1/chat/completions",
        max_retries=2,
        retry_backoff_seconds=0,
    )

    try:
        asyncio.run(provider.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="model",
            api_key="key",
        ))
    except FakeHTTPStatusError:
        pass
    else:
        raise AssertionError("Expected non-retryable provider status to be raised")

    assert len(client.calls) == 1


def test_openai_compatible_provider_does_not_retry_unclassified_errors():
    client = SequenceClient([ValueError("bad payload")])
    provider = OpenAICompatibleProvider(
        client=client,
        api_url="https://provider.example/v1/chat/completions",
        max_retries=2,
        retry_backoff_seconds=0,
    )

    try:
        asyncio.run(provider.chat(
            messages=[{"role": "user", "content": "hi"}],
            model="model",
            api_key="key",
        ))
    except ValueError:
        pass
    else:
        raise AssertionError("Expected unclassified provider error to be raised")

    assert len(client.calls) == 1


def test_planner_call_llm_with_tools_reuses_shared_client():
    from plugins.arteta_agent import planner

    created = []

    def factory():
        client = FakeClient([], {"role": "assistant", "content": "ok"})
        created.append(client)
        return client

    set_shared_async_client_factory(factory)
    try:
        first = asyncio.run(planner.call_llm_with_tools(
            [{"role": "user", "content": "one"}],
            "model",
            "key",
        ))
        second = asyncio.run(planner.call_llm_with_tools(
            [{"role": "user", "content": "two"}],
            "model",
            "key",
        ))

        assert first == {"role": "assistant", "content": "ok"}
        assert second == {"role": "assistant", "content": "ok"}
        assert len(created) == 1
        assert len(created[0].calls) == 2
    finally:
        asyncio.run(close_shared_async_client())
        set_shared_async_client_factory(None)


def test_activation_llm_uses_shared_provider_client():
    from plugins.arteta_agent.activation import call_activation_llm

    calls = []
    client = FakeClient(
        calls,
        {"role": "assistant", "content": "{\"should_reply\": true, \"reason\": \"task\"}"},
    )
    set_shared_async_client_factory(lambda: client)
    try:
        result = asyncio.run(call_activation_llm(
            [{"role": "user", "content": "hi"}],
            "model",
            "key",
            timeout=4.0,
            api_url="https://provider.example/v1/chat/completions",
        ))

        assert result == "{\"should_reply\": true, \"reason\": \"task\"}"
        assert calls[0][0] == "https://provider.example/v1/chat/completions"
        assert calls[0][2]["temperature"] == 0
        assert calls[0][2]["max_tokens"] == 80
        assert calls[0][2]["response_format"] == {"type": "json_object"}
        assert calls[0][3] == 4.0
    finally:
        asyncio.run(close_shared_async_client())
        set_shared_async_client_factory(None)


def test_bot_entry_registers_provider_client_shutdown_hook():
    source = Path("bot.py").read_text(encoding="utf-8")

    assert "close_shared_async_client" in source
    assert "driver.on_shutdown(close_shared_async_client)" in source


def test_planner_provider_call_uses_fixed_adapter_protocol():
    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "inspect.signature(call_llm_with_tools)" not in source
