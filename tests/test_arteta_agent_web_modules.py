import asyncio
import logging

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


def test_web_access_compatibility_module_delegates_to_web_handlers():
    from plugins.arteta_agent.tools import web_access
    from plugins.arteta_agent.tools.web import handlers

    assert web_access is handlers
    assert web_access.web_fetch is handlers.web_fetch
    assert web_access.web_search is handlers.web_search
    assert web_access.grok_search is handlers.grok_search
    assert web_access.fetch_x_post is handlers.fetch_x_post
    assert web_access.verify_recent_claim is handlers.verify_recent_claim
    assert web_access.register_tools is handlers.register_tools


def test_web_security_helpers_are_extracted_but_compatibly_exported():
    from plugins.arteta_agent.tools import web_access
    from plugins.arteta_agent.tools.web import handlers, security

    assert web_access._safe_url is security._safe_url
    assert handlers._safe_url is security._safe_url
    assert handlers._validate_public_http_url is security._validate_public_http_url
    assert handlers._has_sensitive_remote_query is security._has_sensitive_remote_query
    assert handlers._is_allowed_text_content_type is security._is_allowed_text_content_type


def test_search_web_uses_search_backend_abstraction(monkeypatch):
    from plugins.arteta_agent.tools.web import handlers
    from plugins.arteta_agent.tools.web.models import SearchHit

    calls = []

    class FakeBackend(object):
        name = "fake"

        async def search(self, query, max_results, freshness, budget):
            calls.append((query, max_results, freshness))
            return [SearchHit(
                title="Backend source",
                url="https://www.arsenal.com/news/backend",
                snippet="Backend abstraction result.",
                backend="fake",
            )]

    monkeypatch.setattr(handlers, "_search_backends_for_request", lambda freshness, timelimit, **_kwargs: [FakeBackend()])

    result = asyncio.run(handlers._search_web("Arsenal", max_results=2, freshness="recent", timelimit="m"))

    assert calls == [("Arsenal", 2, "recent")]
    assert result == [{
        "title": "Backend source",
        "href": "https://www.arsenal.com/news/backend",
        "body": "Backend abstraction result.",
        "_backend": "fake",
    }]


def test_x_reader_helpers_are_extracted_but_compatibly_exported():
    from plugins.arteta_agent.tools.web import handlers, x_reader

    assert handlers._x_status_id is x_reader._x_status_id
    assert handlers._x_username is x_reader._x_username
    assert handlers._is_x_status_url is x_reader._is_x_status_url
    assert handlers._extract_x_text is x_reader._extract_x_text
    assert handlers._extract_x_author is x_reader._extract_x_author
    assert handlers._x_mirror_urls is x_reader._x_mirror_urls
    assert handlers._format_x_mirror_page is x_reader._format_x_mirror_page
    assert handlers._format_x_post is x_reader._format_x_post


def test_verification_helpers_are_extracted_but_compatibly_exported():
    from plugins.arteta_agent.tools.web import handlers, verification

    assert handlers._VerificationEvidence is verification._VerificationEvidence
    assert handlers._domain is verification._domain
    assert handlers._source_level is verification._source_level
    assert handlers._claim_result_score is verification._claim_result_score
    assert handlers._classify_evidence_stance is verification._classify_evidence_stance
    assert handlers._select_verification_verdict is verification._select_verification_verdict
    assert handlers._format_verification_result is verification._format_verification_result


def test_fetch_helpers_are_extracted_with_compatible_fetch_wrapper():
    from plugins.arteta_agent.tools.web import fetch, handlers

    assert handlers.PageExtractor is fetch.PageExtractor
    assert handlers._parse_page is fetch._parse_page
    assert handlers._format_page_evidence is fetch._format_page_evidence
    assert handlers._read_limited_response is fetch._read_limited_response
    assert handlers._fetch_url_impl is fetch._fetch_url


def test_search_parsers_are_extracted_but_compatibly_exported():
    from plugins.arteta_agent.tools.web import handlers
    from plugins.arteta_agent.tools.web.parsers import bing, duckduckgo, grok, markdown

    assert handlers._normalize_bing_href is bing._normalize_bing_href
    assert handlers._parse_bing_html is bing._parse_bing_html
    assert handlers._normalize_duckduckgo_href is duckduckgo._normalize_duckduckgo_href
    assert handlers._parse_duckduckgo_html is duckduckgo._parse_duckduckgo_html
    assert handlers._parse_markdown_search_results is markdown._parse_markdown_search_results
    assert handlers._parse_groksearch_search_response is grok._parse_groksearch_search_response
    assert handlers._parse_groksearch_content_links is grok._parse_groksearch_content_links
    assert handlers._parse_groksearch_sources_response is grok._parse_groksearch_sources_response


def test_web_registration_is_extracted_but_compatibly_exported():
    from plugins.arteta_agent.tools.web import handlers, registration

    assert handlers.register_tools is registration.register_tools


def test_web_formatting_is_extracted_but_compatibly_exported():
    from plugins.arteta_agent.tools.web import formatting, handlers

    assert handlers._is_grok_result is formatting._is_grok_result
    assert handlers._format_search_results is formatting._format_search_results


def test_search_backends_share_explicit_time_budget():
    from plugins.arteta_agent.tools.web.models import SearchHit
    from plugins.arteta_agent.tools.web.search_backends import TimeBudget, run_search_backends

    now = [10.0]
    calls = []
    budget = TimeBudget(5.0, now_func=lambda: now[0])

    class FailingBackend(object):
        name = "first"
        timeout_seconds = 30.0

        async def search(self, query, max_results, freshness, budget):
            calls.append(("first", round(budget.remaining(), 2)))
            now[0] = 13.5
            raise RuntimeError("transient backend failure")

    class WorkingBackend(object):
        name = "second"
        timeout_seconds = 30.0

        async def search(self, query, max_results, freshness, budget):
            calls.append(("second", round(budget.remaining(), 2)))
            return [SearchHit("Budgeted source", "https://www.arsenal.com/news/budget")]

    result = asyncio.run(run_search_backends(
        [FailingBackend(), WorkingBackend()],
        query="Arsenal",
        max_results=1,
        freshness="recent",
        budget=budget,
    ))

    assert calls == [("first", 5.0), ("second", 1.5)]
    assert result[0].title == "Budgeted source"


def test_legacy_search_chain_uses_concrete_backend_classes(monkeypatch):
    from plugins.arteta_agent.tools.web import handlers
    from plugins.arteta_agent.tools.web.search_backends import (
        BingHtmlBackend,
        DDGSBackend,
        DuckDuckGoHtmlBackend,
        JinaSearchBackend,
    )

    monkeypatch.delenv("ARTETA_WEB_SEARCH_USE_DDGS", raising=False)
    backends = handlers._legacy_search_backends(timelimit="m")

    assert [type(backend) for backend in backends] == [
        BingHtmlBackend,
        DuckDuckGoHtmlBackend,
        JinaSearchBackend,
    ]

    monkeypatch.setenv("ARTETA_WEB_SEARCH_USE_DDGS", "1")
    backends_with_ddgs = handlers._legacy_search_backends(timelimit="m")
    assert isinstance(backends_with_ddgs[-1], DDGSBackend)


def test_duckduckgo_search_fallback_uses_concrete_backends(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    calls = []

    async def fake_bing(query, max_results):
        calls.append("bing")
        return "<html></html>"

    async def fake_duckduckgo(query, max_results):
        calls.append("duckduckgo")
        return "<html></html>"

    async def fake_jina(query, max_results):
        calls.append("jina")
        return "## [Arsenal](https://www.arsenal.com/news)\nOfficial source."

    monkeypatch.setattr(web_access, "_fetch_bing_html", fake_bing)
    monkeypatch.setattr(web_access, "_fetch_duckduckgo_html", fake_duckduckgo)
    monkeypatch.setattr(web_access, "_fetch_jina_duckduckgo_markdown", fake_jina)

    result = asyncio.run(web_access._duckduckgo_search("Arsenal", max_results=2))

    assert calls == ["bing", "duckduckgo", "jina"]
    assert result == [{
        "title": "Arsenal",
        "href": "https://www.arsenal.com/news",
        "body": "Official source.",
        "_backend": "jina",
    }]


def test_search_backend_failure_logs_are_sanitized(caplog):
    from plugins.arteta_agent.tools.web.models import SearchHit
    from plugins.arteta_agent.tools.web.search_backends import run_search_backends

    class FailingBackend(object):
        name = "bad"
        timeout_seconds = None

        async def search(self, query, max_results, freshness, budget):
            raise RuntimeError("secret token=abc123 https://private.example/path")

    class WorkingBackend(object):
        name = "good"
        timeout_seconds = None

        async def search(self, query, max_results, freshness, budget):
            return [SearchHit("Clean source", "https://www.arsenal.com/news/clean")]

    caplog.set_level(logging.WARNING, logger="plugins.arteta_agent.tools.web.search_backends")

    result = asyncio.run(run_search_backends(
        [FailingBackend(), WorkingBackend()],
        query="Arsenal token=abc123",
        max_results=1,
        freshness="recent",
    ))

    assert result[0].title == "Clean source"
    assert "web_search_backend_failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "abc123" not in caplog.text
    assert "private.example" not in caplog.text


def test_remote_fetch_proxy_failure_logs_are_sanitized(monkeypatch, caplog):
    from plugins.arteta_agent.tools import web_access

    async def fail_local_fetch(url, timeout_seconds=10.0, max_bytes=500000):
        raise RuntimeError("local fetch failed")

    async def fail_grok_fetch(url):
        raise RuntimeError("secret token=abc123 https://private.example/path")

    monkeypatch.setattr(web_access, "_fetch_url", fail_local_fetch)
    monkeypatch.setattr(web_access, "_remote_fetch_proxy_enabled", lambda: True)
    monkeypatch.setattr(web_access, "_groksearch_enabled", lambda: True)
    monkeypatch.setattr(web_access, "_validate_public_http_url", lambda url: object())
    monkeypatch.setattr(web_access, "_groksearch_fetch", fail_grok_fetch)

    caplog.set_level(logging.WARNING, logger="plugins.arteta_agent.tools.web.handlers")

    result = asyncio.run(web_access.web_fetch(make_context(), url="https://www.arsenal.com/news/proxy"))

    assert result.status == "error"
    assert "web_access_fallback_failed event=remote_fetch_proxy" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "abc123" not in caplog.text
    assert "private.example" not in caplog.text


def test_verify_recent_claim_fetch_failure_logs_are_sanitized(monkeypatch, caplog):
    from plugins.arteta_agent.tools import web_access

    async def fake_search(query, max_results=5, freshness="recent", timelimit=None):
        return [{
            "title": "Arsenal official update",
            "href": "https://www.arsenal.com/news/update",
            "body": "Official source snippet.",
        }]

    async def fail_fetch(url, timeout_seconds=10.0, max_bytes=500000):
        raise RuntimeError("secret token=abc123 https://private.example/path")

    monkeypatch.setattr(web_access, "_search_web", fake_search)
    monkeypatch.setattr(web_access, "_fetch_url", fail_fetch)
    caplog.set_level(logging.WARNING, logger="plugins.arteta_agent.tools.web.handlers")

    result = asyncio.run(web_access.verify_recent_claim(make_context(), claim="Arsenal official update"))

    assert result.status == "ok"
    assert "web_access_fallback_failed event=verify_recent_claim" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "abc123" not in caplog.text
    assert "private.example" not in caplog.text


def test_grok_snapshot_failure_logs_are_sanitized(monkeypatch, caplog):
    from plugins.arteta_agent.tools import web_access

    async def fake_write_snapshot(page, source_url):
        if "first" in source_url:
            raise RuntimeError("secret token=abc123 https://private.example/path")
        return "artifacts/agent_tools/link_snapshots/second.png"

    monkeypatch.setattr(web_access, "_write_grok_snapshot_image", fake_write_snapshot)
    caplog.set_level(logging.WARNING, logger="plugins.arteta_agent.tools.web.handlers")

    marker = asyncio.run(web_access._grok_source_snapshot_marker([
        "https://www.arsenal.com/news/first",
        "https://www.arsenal.com/news/second",
    ]))

    assert marker == "[LinkSnapshotImage: artifacts/agent_tools/link_snapshots/second.png]"
    assert "web_access_fallback_failed event=grok_snapshot" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "abc123" not in caplog.text
    assert "private.example" not in caplog.text


def test_fetch_x_post_reports_stable_provenance(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    async def fake_x_bridge(url):
        return {
            "url": url,
            "author_name": "David Ornstein",
            "author_username": "David_Ornstein",
            "text": "Original X text from authenticated bridge.",
            "backend": "playwright-profile",
        }

    async def fail_public_path(*args, **kwargs):
        raise AssertionError("public fallback should not run when bridge succeeds")

    monkeypatch.setattr(web_access, "_x_fetch_bridge_enabled", lambda: True)
    monkeypatch.setattr(web_access, "_x_fetch_bridge_fetch", fake_x_bridge)
    monkeypatch.setattr(web_access, "_fetch_x_syndication", fail_public_path)

    result = asyncio.run(web_access.fetch_x_post(
        make_context(),
        url="https://x.com/David_Ornstein/status/2074251813545742720",
    ))

    assert result.status == "ok"
    assert "provenance: configured_bridge" in result.content
    assert "bridge_backend: playwright-profile" in result.content


def test_grok_x_fallback_is_generated_extraction_not_fake_author(monkeypatch):
    from plugins.arteta_agent.tools import web_access

    async def empty_x_syndication(tweet_id):
        return {}

    async def empty_x_mirror(url):
        return {}

    async def fake_grok_fetch(url):
        return "Generated extraction of the X post text."

    monkeypatch.setattr(web_access, "_fetch_x_syndication", empty_x_syndication)
    monkeypatch.setattr(web_access, "_fetch_x_mirror", empty_x_mirror)
    monkeypatch.setattr(web_access, "_groksearch_fetch", fake_grok_fetch)
    monkeypatch.setattr(web_access, "GROKSEARCH_API_URL", "https://grok.example")
    monkeypatch.setattr(web_access, "GROKSEARCH_API_KEY", "sk-test")

    result = asyncio.run(web_access.fetch_x_post(
        make_context(),
        url="https://x.com/David_Ornstein/status/2074251813545742720",
    ))

    assert result.status == "ok"
    assert "provenance: generated_extraction" in result.content
    assert "GrokSearch" not in result.content.split("正文：", 1)[0]
