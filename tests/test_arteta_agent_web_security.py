import asyncio
import inspect
import socket

import pytest

from plugins.arteta_agent.context import ToolContext


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
    }
    data.update(overrides)
    return ToolContext(**data)


class _FakeStreamResponse(object):
    def __init__(self, url, status_code=200, headers=None, body=b""):
        self.url = url
        self.status_code = status_code
        self.headers = headers or {"content-type": "text/html"}
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308)

    def raise_for_status(self):
        return None

    async def aiter_bytes(self):
        yield self._body


def _public_dns(host, port, *args, **kwargs):
    return [(
        socket.AF_INET,
        socket.SOCK_STREAM,
        6,
        "",
        ("93.184.216.34", int(port or 443)),
    )]


def test_fetch_url_rejects_dns_resolving_to_private_ip_before_request(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    class Client(object):
        def stream(self, *args, **kwargs):
            raise AssertionError("unsafe DNS target must be rejected before HTTP request")

    def private_dns(host, port, *args, **kwargs):
        return [(
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            ("127.0.0.1", int(port or 443)),
        )]

    monkeypatch.setattr(socket, "getaddrinfo", private_dns)
    monkeypatch.setattr(web_access, "_http_client", lambda: Client())

    with pytest.raises(ValueError) as exc:
        asyncio.run(web_access._fetch_url("https://public.example/page"))

    assert "URL 不安全" in str(exc.value)


def test_fetch_url_revalidates_each_redirect_before_request(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    calls = []

    class Client(object):
        def stream(self, method, url, **kwargs):
            assert kwargs.get("follow_redirects") is False
            calls.append(url)
            if len(calls) == 1:
                return _FakeStreamResponse(
                    url,
                    status_code=302,
                    headers={"location": "https://127.0.0.1/latest", "content-type": "text/html"},
                )
            raise AssertionError("private redirect target must not receive an HTTP request")

    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    monkeypatch.setattr(web_access, "_http_client", lambda: Client())

    with pytest.raises(ValueError) as exc:
        asyncio.run(web_access._fetch_url("https://public.example/start"))

    assert calls == ["https://public.example/start"]
    assert "URL 不安全" in str(exc.value)


def test_web_search_does_not_append_grok_snapshot_marker(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    async def fake_grok_search(query, max_results, freshness="recent"):
        return [{
            "title": "GrokSearch Arsenal source",
            "href": "https://www.arsenal.com/news/grok",
            "body": "Fresh result from GrokSearch.",
            "_backend": "grok",
        }]

    async def forbidden_snapshot(urls):
        raise AssertionError("safe_read search must not create snapshot artifacts")

    monkeypatch.setattr(web_access, "GROKSEARCH_API_URL", "https://grok.example")
    monkeypatch.setattr(web_access, "GROKSEARCH_API_KEY", "sk-test")
    monkeypatch.setattr(web_access, "_groksearch_search", fake_grok_search)
    monkeypatch.setattr(web_access, "_grok_source_snapshot_marker", forbidden_snapshot)

    result = asyncio.run(web_access.web_search(make_context(), query="Arsenal official news", max_results=2))

    assert result.status == "ok"
    assert "GrokSearch Arsenal source" in result.content
    assert "[LinkSnapshotImage:" not in result.content


def test_web_tool_registration_has_schema_bounds_and_explicit_parallel_metadata():
    from plugins.arteta_agent.registry import clear_registry, list_enabled_tools
    from plugins.arteta_agent.tools import register_phase2_tools

    clear_registry()
    register_phase2_tools()
    tools = {tool.name: tool for tool in list_enabled_tools()}

    for name in ("grok_search", "web_search"):
        query_schema = tools[name].parameters["properties"]["query"]
        max_results_schema = tools[name].parameters["properties"]["max_results"]
        assert tools[name].parameters["additionalProperties"] is False
        assert query_schema["minLength"] == 1
        assert query_schema["maxLength"] == 500
        assert max_results_schema["minimum"] == 1
        assert max_results_schema["maximum"] == 8
        assert tools[name].parallel_safe is True
        assert tools[name].concurrency_group == "web_http"

    fetch_url_schema = tools["web_fetch"].parameters["properties"]["url"]
    assert fetch_url_schema["minLength"] == 8
    assert fetch_url_schema["maxLength"] == 2048
    assert tools["web_fetch"].parameters["properties"]["max_chars"]["maximum"] == 4000

    claim_schema = tools["verify_recent_claim"].parameters["properties"]["claim"]
    assert claim_schema["minLength"] == 1
    assert claim_schema["maxLength"] == 1000
    assert tools["verify_recent_claim"].parameters["properties"]["max_results"]["minimum"] == 2


def test_verify_recent_claim_does_not_claim_verdict_for_single_candidate(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    async def fake_search(query, max_results=5, freshness="recent", timelimit=None):
        return [{
            "title": "Arsenal update",
            "href": "https://example.com/arsenal-update",
            "body": "A candidate source mentions Arsenal.",
        }]

    async def fake_fetch(url, timeout_seconds=10.0, max_bytes=500000):
        return {
            "url": url,
            "final_url": url,
            "content_type": "text/html",
            "text": "<html><head><title>Candidate</title></head><body>Candidate source text.</body></html>",
        }

    monkeypatch.setattr(web_access, "_search_web", fake_search)
    monkeypatch.setattr(web_access, "_fetch_url", fake_fetch)

    result = asyncio.run(web_access.verify_recent_claim(make_context(), claim="Arsenal made a current announcement"))

    assert "已找到可核查来源" not in result.content
    assert "核验结论：不明确" in result.content
    assert "unclear" in result.markers


def test_claim_ranking_has_no_task_specific_entity_hardcodes():
    from plugins.arteta_agent.tools import web_access

    source = inspect.getsource(web_access._claim_result_score)

    assert "阿根廷" not in source
    assert "佛得角" not in source
    assert "cape verde" not in source.lower()
    assert "cabo verde" not in source.lower()


def test_remote_proxy_clients_do_not_follow_redirects(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    calls = []

    class Response(object):
        def raise_for_status(self):
            return None

        def json(self):
            return {}

    class Client(object):
        async def post(self, url, **kwargs):
            calls.append((url, kwargs.get("follow_redirects")))
            return Response()

    monkeypatch.setattr(web_access, "_http_client", lambda: Client())
    monkeypatch.setattr(web_access, "GROKSEARCH_API_URL", "https://grok.example")
    monkeypatch.setattr(web_access, "GROKSEARCH_API_KEY", "sk-test")
    monkeypatch.setattr(web_access, "X_FETCH_API_URL", "https://bridge.example")
    monkeypatch.setattr(web_access, "X_FETCH_API_KEY", "bridge-key")

    asyncio.run(web_access._groksearch_post("web_search", {"query": "arsenal"}))
    asyncio.run(web_access._x_fetch_bridge_fetch("https://x.com/Arsenal/status/123"))

    assert calls == [
        ("https://grok.example/web_search", False),
        ("https://bridge.example/fetch", False),
    ]
