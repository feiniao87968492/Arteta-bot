import asyncio

from plugins.arteta_agent.context import ToolContext
from plugins.arteta_agent.result import TOOL_STATUS_OK, ToolResult


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


def _html(title, body):
    return "<html><head><title>{0}</title></head><body><article>{1}</article></body></html>".format(title, body)


def test_verify_recent_claim_supported_by_official_source(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    async def fake_search(query, max_results=5, freshness="recent", timelimit=None):
        return [{
            "title": "Arsenal official transfer update",
            "href": "https://www.arsenal.com/news/player-a-signs",
            "body": "Arsenal signed Player A.",
        }]

    async def fake_fetch(url, timeout_seconds=10.0, max_bytes=500000):
        return {
            "url": url,
            "final_url": url,
            "content_type": "text/html",
            "text": _html("Official update", "Arsenal signed Player A after the medical was completed."),
        }

    monkeypatch.setattr(web_access, "_search_web", fake_search)
    monkeypatch.setattr(web_access, "_fetch_url", fake_fetch)

    result = asyncio.run(web_access.verify_recent_claim(make_context(), claim="Arsenal signed Player A"))

    assert isinstance(result, ToolResult)
    assert result.status == TOOL_STATUS_OK
    assert "核验结论：支持" in result.content
    assert "supported" in result.markers
    assert "https://www.arsenal.com/news/player-a-signs" in result.content


def test_verify_recent_claim_refuted_by_official_source(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    async def fake_search(query, max_results=5, freshness="recent", timelimit=None):
        return [{
            "title": "Arsenal official clarification",
            "href": "https://www.arsenal.com/news/player-a-clarification",
            "body": "Arsenal did not sign Player A.",
        }]

    async def fake_fetch(url, timeout_seconds=10.0, max_bytes=500000):
        return {
            "url": url,
            "final_url": url,
            "content_type": "text/html",
            "text": _html("Official clarification", "Arsenal did not sign Player A and reports claiming otherwise are false."),
        }

    monkeypatch.setattr(web_access, "_search_web", fake_search)
    monkeypatch.setattr(web_access, "_fetch_url", fake_fetch)

    result = asyncio.run(web_access.verify_recent_claim(make_context(), claim="Arsenal signed Player A"))

    assert result.status == TOOL_STATUS_OK
    assert "核验结论：反驳" in result.content
    assert "refuted" in result.markers


def test_verify_recent_claim_unclear_with_single_ordinary_source(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    async def fake_search(query, max_results=5, freshness="recent", timelimit=None):
        return [{
            "title": "Transfer blog",
            "href": "https://example.com/player-a-rumour",
            "body": "Arsenal signed Player A according to a blog.",
        }]

    async def fake_fetch(url, timeout_seconds=10.0, max_bytes=500000):
        return {
            "url": url,
            "final_url": url,
            "content_type": "text/html",
            "text": _html("Rumour blog", "Arsenal signed Player A according to unnamed sources."),
        }

    monkeypatch.setattr(web_access, "_search_web", fake_search)
    monkeypatch.setattr(web_access, "_fetch_url", fake_fetch)

    result = asyncio.run(web_access.verify_recent_claim(make_context(), claim="Arsenal signed Player A"))

    assert "核验结论：不明确" in result.content
    assert "ordinary source" in result.content
    assert "unclear" in result.markers


def test_verify_recent_claim_unclear_when_authoritative_sources_conflict(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    async def fake_search(query, max_results=5, freshness="recent", timelimit=None):
        return [
            {
                "title": "Arsenal official update",
                "href": "https://www.arsenal.com/news/player-a-signs",
                "body": "Arsenal signed Player A.",
            },
            {
                "title": "BBC transfer clarification",
                "href": "https://www.bbc.com/sport/football/player-a",
                "body": "Arsenal did not sign Player A.",
            },
        ]

    async def fake_fetch(url, timeout_seconds=10.0, max_bytes=500000):
        if "arsenal.com" in url:
            body = "Arsenal signed Player A after the medical was completed."
        else:
            body = "Arsenal did not sign Player A, according to the latest BBC report."
        return {
            "url": url,
            "final_url": url,
            "content_type": "text/html",
            "text": _html("Evidence", body),
        }

    monkeypatch.setattr(web_access, "_search_web", fake_search)
    monkeypatch.setattr(web_access, "_fetch_url", fake_fetch)

    result = asyncio.run(web_access.verify_recent_claim(make_context(), claim="Arsenal signed Player A"))

    assert "核验结论：不明确" in result.content
    assert "来源冲突" in result.content
    assert "unclear" in result.markers


def test_verify_recent_claim_does_not_trust_search_snippet_only(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    async def fake_search(query, max_results=5, freshness="recent", timelimit=None):
        return [{
            "title": "Arsenal official update",
            "href": "https://www.arsenal.com/news/player-a-signs",
            "body": "Arsenal signed Player A.",
        }]

    async def failing_fetch(url, timeout_seconds=10.0, max_bytes=500000):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(web_access, "_search_web", fake_search)
    monkeypatch.setattr(web_access, "_fetch_url", failing_fetch)

    result = asyncio.run(web_access.verify_recent_claim(make_context(), claim="Arsenal signed Player A"))

    assert "核验结论：不明确" in result.content
    assert "搜索摘要不能单独确认" in result.content
    assert "supported" not in result.markers
