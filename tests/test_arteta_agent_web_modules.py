import asyncio


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

        async def search(self, query, max_results, freshness):
            calls.append((query, max_results, freshness))
            return [SearchHit(
                title="Backend source",
                url="https://www.arsenal.com/news/backend",
                snippet="Backend abstraction result.",
                backend="fake",
            )]

    monkeypatch.setattr(handlers, "_search_backends_for_request", lambda freshness, timelimit: [FakeBackend()])

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
