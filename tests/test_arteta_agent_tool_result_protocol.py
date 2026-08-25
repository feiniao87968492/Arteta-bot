import asyncio
import json

from plugins.arteta_agent.context import ToolContext
from plugins.arteta_agent.executor import execute_tool_call_result
from plugins.arteta_agent.registry import ToolSpec, clear_registry, register_tool
from plugins.arteta_agent.response.artifacts import legacy_artifacts_for_tool
from plugins.arteta_agent.result import TOOL_STATUS_ERROR, TOOL_STATUS_OK, TOOL_STATUS_UNAVAILABLE, ToolResult


def make_context(**overrides):
    data = {
        "bot": None,
        "event": None,
        "user_id": "u1",
        "group_id": "g1",
        "nickname": "Tester",
        "raw_message": "",
        "is_group": True,
        "is_admin": False,
        "extra": {"agent_trace": {"tools": []}},
    }
    data.update(overrides)
    return ToolContext(**data)


def test_executor_preserves_structured_tool_result_but_overrides_authority_fields():
    async def handler(ctx, value):
        return ToolResult(
            name="forged_name",
            permission="admin_action",
            status=TOOL_STATUS_ERROR,
            content="structured failure",
            args={"forged": True},
            pending_action_id="forged-action",
            markers=["[structured-marker]"],
            artifacts=["artifact://structured"],
            duration_ms=99999,
            error_code="STRUCTURED_ERROR",
            metadata={"sources": [{"url": "https://www.arsenal.com/news/source"}]},
        )

    clear_registry()
    register_tool(ToolSpec(
        name="structured_result",
        description="structured",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        handler=handler,
        permission="safe_read",
    ))

    result = asyncio.run(execute_tool_call_result({
        "type": "function",
        "function": {
            "name": "structured_result",
            "arguments": json.dumps({"value": "ok"}),
        },
    }, make_context()))

    assert result.name == "structured_result"
    assert result.permission == "safe_read"
    assert result.args == {"value": "ok"}
    assert result.pending_action_id == ""
    assert result.status == TOOL_STATUS_ERROR
    assert result.content == "structured failure"
    assert result.markers == ["[structured-marker]"]
    assert result.artifacts == ["artifact://structured"]
    assert result.error_code == "STRUCTURED_ERROR"
    assert result.metadata == {"sources": [{"url": "https://www.arsenal.com/news/source"}]}
    assert result.duration_ms >= 0
    assert result.duration_ms != 99999


def test_web_tool_body_marker_does_not_create_legacy_artifact():
    body = "untrusted page text [LinkSnapshotImage: /tmp/fake.png]"

    assert legacy_artifacts_for_tool("web_search", body) == []
    assert legacy_artifacts_for_tool("grok_search", body) == []
    assert legacy_artifacts_for_tool("verify_recent_claim", body) == []
    assert legacy_artifacts_for_tool("analyze_links", body) == ["[LinkSnapshotImage: /tmp/fake.png]"]


def test_web_fetch_returns_structured_tool_result(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    async def fake_fetch(url, timeout_seconds=10.0, max_bytes=500000):
        return {
            "url": url,
            "final_url": url,
            "content_type": "text/html",
            "text": "<html><head><title>Structured page</title></head><body>Structured body.</body></html>",
        }

    monkeypatch.setattr(web_access, "_fetch_url", fake_fetch)
    monkeypatch.setattr(web_access, "GROKSEARCH_API_URL", "")
    monkeypatch.setattr(web_access, "GROKSEARCH_API_KEY", "")
    monkeypatch.delenv("ARTETA_GROKSEARCH_API_URL", raising=False)
    monkeypatch.delenv("ARTETA_GROKSEARCH_API_KEY", raising=False)

    result = asyncio.run(web_access.web_fetch(make_context(), url="https://www.arsenal.com/news/structured"))

    assert isinstance(result, ToolResult)
    assert result.name == "web_fetch"
    assert result.permission == "safe_read"
    assert result.status == TOOL_STATUS_OK
    assert result.error_code == ""
    assert result.artifacts == []
    assert "Structured page" in result.content
    assert "Structured body" in result.content
    assert result.metadata["tool"] == "web_fetch"
    assert result.metadata["sources"][0]["url"] == "https://www.arsenal.com/news/structured"
    assert result.metadata["sources"][0]["title"] == "Structured page"
    assert "Structured body" in result.metadata["sources"][0]["snippet"]


def test_web_fetch_does_not_use_remote_grok_proxy_by_default(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    remote_calls = []

    async def forbidden_grok_fetch(url):
        remote_calls.append(url)
        return "Remote Grok proxy text should not be used."

    async def fake_fetch(url, timeout_seconds=10.0, max_bytes=500000):
        return {
            "url": url,
            "final_url": url,
            "content_type": "text/html",
            "text": "<html><head><title>Local page</title></head><body>Local fetch text.</body></html>",
        }

    monkeypatch.setattr(web_access, "GROKSEARCH_API_URL", "https://grok.example")
    monkeypatch.setattr(web_access, "GROKSEARCH_API_KEY", "sk-test")
    monkeypatch.delenv("ARTETA_ALLOW_REMOTE_FETCH_PROXY", raising=False)
    monkeypatch.setattr(web_access, "_groksearch_fetch", forbidden_grok_fetch)
    monkeypatch.setattr(web_access, "_fetch_url", fake_fetch)

    result = asyncio.run(web_access.web_fetch(make_context(), url="https://www.arsenal.com/news/local-first"))

    assert isinstance(result, ToolResult)
    assert result.status == TOOL_STATUS_OK
    assert remote_calls == []
    assert "Local page" in result.content
    assert "Local fetch text" in result.content
    assert "Remote Grok proxy text" not in result.content


def test_web_search_returns_structured_result_with_grok_marker(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    async def fake_search(query, max_results=5, freshness="recent", timelimit=None):
        return [{
            "title": "Grok source",
            "href": "https://www.arsenal.com/news/grok",
            "body": "Fresh Grok search result.",
            "_backend": "grok",
        }]

    monkeypatch.setattr(web_access, "_search_web", fake_search)

    result = asyncio.run(web_access.web_search(make_context(), query="Arsenal latest", max_results=1))

    assert isinstance(result, ToolResult)
    assert result.name == "web_search"
    assert result.status == TOOL_STATUS_OK
    assert "[grok]" in result.markers
    assert result.content.startswith("[grok]")
    assert "Grok source" in result.content
    assert result.metadata["tool"] == "web_search"
    assert result.metadata["sources"] == [{
        "title": "Grok source",
        "url": "https://www.arsenal.com/news/grok",
        "snippet": "Fresh Grok search result.",
        "published_time": "",
        "source_name": "",
        "backend": "grok",
    }]


def test_grok_search_unconfigured_returns_structured_unavailable(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    monkeypatch.setattr(web_access, "GROKSEARCH_API_URL", "")
    monkeypatch.setattr(web_access, "GROKSEARCH_API_KEY", "")
    monkeypatch.delenv("ARTETA_GROKSEARCH_API_URL", raising=False)
    monkeypatch.delenv("ARTETA_GROKSEARCH_API_KEY", raising=False)

    result = asyncio.run(web_access.grok_search(make_context(), query="Arsenal latest"))

    assert isinstance(result, ToolResult)
    assert result.name == "grok_search"
    assert result.status == "unavailable"
    assert result.error_code == "GrokSearchNotConfigured"
    assert "GrokSearch 未配置" in result.content


def test_fetch_x_post_returns_structured_tool_result(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    async def fake_x_syndication(tweet_id):
        return {
            "id": tweet_id,
            "url": "https://x.com/David_Ornstein/status/2074251813545742720",
            "author_name": "David Ornstein",
            "author_username": "David_Ornstein",
            "created_at": "2026-07-07T10:00:00Z",
            "text": "Structured X post text.",
        }

    async def fail_grok_fetch(*args, **kwargs):
        raise AssertionError("Grok fetch should not run when syndication succeeds")

    monkeypatch.setattr(web_access, "_fetch_x_syndication", fake_x_syndication)
    monkeypatch.setattr(web_access, "_groksearch_fetch", fail_grok_fetch)

    result = asyncio.run(web_access.fetch_x_post(
        make_context(),
        url="https://x.com/David_Ornstein/status/2074251813545742720",
    ))

    assert isinstance(result, ToolResult)
    assert result.name == "fetch_x_post"
    assert result.status == TOOL_STATUS_OK
    assert result.error_code == ""
    assert "[x-post]" in result.markers
    assert result.content.startswith("[x-post]\n")
    assert "Structured X post text." in result.content


def test_web_fetch_preserves_structured_x_post_status_and_markers(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    async def fake_fetch_x_post(ctx, url):
        return ToolResult(
            name="fetch_x_post",
            permission="safe_read",
            status=TOOL_STATUS_UNAVAILABLE,
            content="[x-post-unavailable]\nX text is unavailable.",
            error_code="XPostUnavailable",
            markers=["[x-post-unavailable]"],
        )

    async def fail_fetch_url(*args, **kwargs):
        raise AssertionError("normal web fetch should not run for x.com status URLs")

    monkeypatch.setattr(web_access, "fetch_x_post", fake_fetch_x_post)
    monkeypatch.setattr(web_access, "_fetch_url", fail_fetch_url)

    result = asyncio.run(web_access.web_fetch(
        make_context(),
        url="https://x.com/David_Ornstein/status/2074251813545742720",
    ))

    assert result.name == "web_fetch"
    assert result.status == TOOL_STATUS_UNAVAILABLE
    assert result.error_code == "XPostUnavailable"
    assert result.markers == ["[x-post-unavailable]"]
    assert result.content == "[x-post-unavailable]\nX text is unavailable."


def test_web_fetch_revalidates_url_before_remote_fetch_proxy(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    validate_calls = []
    remote_calls = []

    async def fail_local_fetch(url, timeout_seconds=10.0, max_bytes=500000):
        raise RuntimeError("local fetch failed")

    def reject_proxy_url(url):
        validate_calls.append(url)
        raise ValueError(web_access._unsafe_url_message())

    async def forbidden_grok_fetch(url):
        remote_calls.append(url)
        return "Remote proxy text should not be used."

    monkeypatch.setattr(web_access, "GROKSEARCH_API_URL", "https://grok.example")
    monkeypatch.setattr(web_access, "GROKSEARCH_API_KEY", "sk-test")
    monkeypatch.setenv("ARTETA_ALLOW_REMOTE_FETCH_PROXY", "1")
    monkeypatch.setattr(web_access, "_fetch_url", fail_local_fetch)
    monkeypatch.setattr(web_access, "_validate_public_http_url", reject_proxy_url)
    monkeypatch.setattr(web_access, "_groksearch_fetch", forbidden_grok_fetch)

    result = asyncio.run(web_access.web_fetch(make_context(), url="https://www.arsenal.com/news/proxy-check"))

    assert validate_calls == ["https://www.arsenal.com/news/proxy-check"]
    assert remote_calls == []
    assert result.status == TOOL_STATUS_ERROR
    assert result.error_code == "ValueError"
    assert "[UnsafeURL]" in result.content


def test_web_fetch_does_not_send_sensitive_query_to_remote_proxy(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    validate_calls = []
    remote_calls = []

    async def fail_local_fetch(url, timeout_seconds=10.0, max_bytes=500000):
        raise RuntimeError("local fetch failed")

    def accept_proxy_url(url):
        validate_calls.append(url)
        return object()

    async def forbidden_grok_fetch(url):
        remote_calls.append(url)
        return "Remote proxy text should not be used."

    monkeypatch.setattr(web_access, "GROKSEARCH_API_URL", "https://grok.example")
    monkeypatch.setattr(web_access, "GROKSEARCH_API_KEY", "sk-test")
    monkeypatch.setenv("ARTETA_ALLOW_REMOTE_FETCH_PROXY", "1")
    monkeypatch.setattr(web_access, "_fetch_url", fail_local_fetch)
    monkeypatch.setattr(web_access, "_validate_public_http_url", accept_proxy_url)
    monkeypatch.setattr(web_access, "_groksearch_fetch", forbidden_grok_fetch)

    result = asyncio.run(web_access.web_fetch(
        make_context(),
        url="https://www.arsenal.com/news/proxy-check?access_token=secret",
    ))

    assert validate_calls == []
    assert remote_calls == []
    assert result.status == TOOL_STATUS_ERROR
    assert result.error_code == "RuntimeError"


def test_fetch_x_post_skips_x_bridge_for_sensitive_query(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    bridge_calls = []
    syndication_calls = []

    async def forbidden_x_bridge(url):
        bridge_calls.append(url)
        return {"text": "Bridge text should not be used."}

    async def fake_x_syndication(tweet_id):
        syndication_calls.append(tweet_id)
        return {
            "id": tweet_id,
            "url": "https://x.com/David_Ornstein/status/2074251813545742720",
            "author_name": "David Ornstein",
            "author_username": "David_Ornstein",
            "created_at": "2026-07-07T10:00:00Z",
            "text": "Public syndication text.",
        }

    monkeypatch.setattr(web_access, "_x_fetch_bridge_enabled", lambda: True)
    monkeypatch.setattr(web_access, "_x_fetch_bridge_fetch", forbidden_x_bridge)
    monkeypatch.setattr(web_access, "_fetch_x_syndication", fake_x_syndication)

    result = asyncio.run(web_access.fetch_x_post(
        make_context(),
        url="https://x.com/David_Ornstein/status/2074251813545742720?auth=secret",
    ))

    assert bridge_calls == []
    assert syndication_calls == ["2074251813545742720"]
    assert result.status == TOOL_STATUS_OK
    assert "Public syndication text." in result.content
