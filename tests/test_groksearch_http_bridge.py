import asyncio
import os
import types

from fastapi import HTTPException

from tools import groksearch_http_bridge as bridge


def test_bridge_loads_env_file_without_shell_parsing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env.prod"
    env_file.write_text(
        "COMMAND_START=['', '/']\n"
        "GROK_API_URL=https://example.com/v1\n"
        "ARTETA_GROKSEARCH_API_KEY=bridge-secret\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GROK_API_URL", raising=False)
    monkeypatch.delenv("ARTETA_GROKSEARCH_API_KEY", raising=False)

    bridge._load_env_file(str(env_file))

    assert os.environ["GROK_API_URL"] == "https://example.com/v1"
    assert os.environ["ARTETA_GROKSEARCH_API_KEY"] == "bridge-secret"


def test_bridge_auth_allows_blank_key(monkeypatch):
    monkeypatch.setattr(bridge, "BRIDGE_API_KEY", "")

    bridge._check_auth("")


def test_bridge_auth_rejects_wrong_bearer(monkeypatch):
    monkeypatch.setattr(bridge, "BRIDGE_API_KEY", "bridge-secret")

    try:
        bridge._check_auth("Bearer wrong")
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("expected HTTPException")


def test_bridge_coerces_string_json_result():
    result = bridge._coerce_json_result('{"session_id":"s1","sources_count":1}')

    assert result == {"session_id": "s1", "sources_count": 1}


def test_bridge_calls_grok_tool(monkeypatch):
    async def fake_web_fetch(url):
        return {"content": "page: " + url}

    fake_server = types.SimpleNamespace(web_fetch=fake_web_fetch)
    monkeypatch.setattr(bridge, "_load_grok_server", lambda: fake_server)

    result = asyncio.run(bridge._call_grok_tool("web_fetch", url="https://example.com"))

    assert result == {"content": "page: https://example.com"}


def test_bridge_calls_wrapped_grok_tool(monkeypatch):
    async def fake_web_search(query, platform="", model="", extra_sources=0):
        return {"content": query, "sources_count": extra_sources}

    fake_tool = types.SimpleNamespace(fn=fake_web_search)
    fake_server = types.SimpleNamespace(web_search=fake_tool)
    monkeypatch.setattr(bridge, "_load_grok_server", lambda: fake_server)

    result = asyncio.run(bridge._call_grok_tool("web_search", query="arsenal", extra_sources=3))

    assert result == {"content": "arsenal", "sources_count": 3}


def test_bridge_filters_unsupported_grok_tool_kwargs(monkeypatch):
    async def fake_web_search(query, platform="", model="", extra_sources=0):
        return {
            "content": query,
            "platform": platform,
            "model": model,
            "sources_count": extra_sources,
        }

    fake_server = types.SimpleNamespace(web_search=fake_web_search)
    monkeypatch.setattr(bridge, "_load_grok_server", lambda: fake_server)

    result = asyncio.run(bridge._call_grok_tool(
        "web_search",
        query="arsenal",
        max_results=5,
        freshness="week",
        platform="Twitter",
        model="grok-4.3-fast",
        extra_sources=3,
    ))

    assert result == {
        "content": "arsenal",
        "platform": "Twitter",
        "model": "grok-4.3-fast",
        "sources_count": 3,
    }


def test_bridge_falls_back_to_project_search_when_grok_package_missing(monkeypatch):
    async def missing_tool(tool_name, **kwargs):
        raise HTTPException(status_code=503, detail="grok_search is not importable: missing")

    async def fake_fallback(query, max_results, freshness="recent", model=""):
        return {"results": [{"title": query, "href": "https://example.com", "body": "fallback"}]}

    monkeypatch.setattr(bridge, "_call_grok_tool", missing_tool)
    monkeypatch.setattr(bridge, "_fallback_web_search", fake_fallback)

    result = asyncio.run(
        bridge._call_grok_tool_or_fallback(
            "web_search",
            query="arsenal",
            max_results=2,
            freshness="recent",
            model="grok-4.3-fast",
        )
    )

    assert result["results"][0]["title"] == "arsenal"


def test_bridge_expands_chinese_match_query_for_fallback_search(monkeypatch):
    queries = []

    class FakeWebAccess(object):
        MAX_SEARCH_RESULTS = 8

        @staticmethod
        def _safe_int(value, default, low, high):
            return max(low, min(high, int(value)))

        @staticmethod
        def _search_result_url(item):
            return item.get("href", "")

        @staticmethod
        def _clean_text(value):
            return str(value or "").strip()

        @staticmethod
        def _safe_url(url):
            return str(url or "").startswith("https://")

        async def _fetch_bing_html(self, query, max_results):
            queries.append(query)
            if "Argentina Cape Verde FIFA World Cup 2026 score result" in query:
                return "MATCH"
            return ""

        def _parse_bing_html(self, html, max_results):
            if html == "MATCH":
                return [{
                    "title": "Argentina 3-2 Cape Verde",
                    "href": "https://www.espn.com/soccer/match/_/gameId/test",
                    "body": "Argentina beat Cape Verde 3-2 after extra time.",
                }]
            return []

        async def _fetch_duckduckgo_html(self, query, max_results):
            raise AssertionError("duckduckgo should not run after expanded Bing query succeeds")

        def _parse_duckduckgo_html(self, html, max_results):
            return []

        async def _fetch_jina_duckduckgo_markdown(self, query, max_results):
            return ""

        def _parse_markdown_search_results(self, markdown, max_results):
            return []

    monkeypatch.setattr(bridge, "_load_project_web_access", lambda: FakeWebAccess())
    async def fake_summary(*args, **kwargs):
        return ""

    monkeypatch.setattr(bridge, "_grok_research_summary", fake_summary)

    result = asyncio.run(bridge._fallback_web_search("阿根廷和佛得角的比赛情况", 5))

    assert any("Argentina Cape Verde FIFA World Cup 2026 score result" in query for query in queries)
    assert result["results"][0]["title"] == "Argentina 3-2 Cape Verde"


def test_bridge_adds_chinese_score_queries_for_english_argentina_cape_verde_match():
    queries = bridge._fallback_search_queries("Argentina Cabo Verde match July 2026 result")

    assert "阿根廷 佛得角 世界杯 比分 3-2" in queries
    assert "阿根廷 佛得角 央视 世界杯 3-2" in queries


def test_bridge_scores_chinese_sports_match_result_above_encyclopedia():
    encyclopedia = {
        "title": "Argentina | Britannica",
        "href": "https://www.britannica.com/place/Argentina",
        "body": "Argentina country profile.",
    }
    match = {
        "title": "[世界杯]1/16决赛： 阿根廷 3-2佛得角 集锦",
        "href": "https://sports.cctv.com/2026/07/04/example.shtml",
        "body": "2026年美加墨世界杯1/16决赛，阿根廷VS佛得角。最终阿根廷通过加时赛以3-2战胜佛得角。",
    }

    assert bridge._result_score("阿根廷和佛得角的比赛情况", match) > bridge._result_score(
        "阿根廷和佛得角的比赛情况",
        encyclopedia,
    )


def test_bridge_scores_match_result_above_team_profile():
    team_profile = {
        "title": "Argentina | FIFA World Cup 2026™",
        "href": "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/teams/argentina/squad",
        "body": "latest news, interviews, key stats, fixtures and results for the Argentina squad",
    }
    match = {
        "title": "[世界杯]1/16决赛： 阿根廷 3-2佛得角 集锦",
        "href": "https://sports.cctv.com/2026/07/04/example.shtml",
        "body": "2026年美加墨世界杯1/16决赛，阿根廷VS佛得角。最终阿根廷通过加时赛以3-2战胜佛得角。",
    }

    assert bridge._result_score("阿根廷和佛得角的比赛情况", match) > bridge._result_score(
        "阿根廷和佛得角的比赛情况",
        team_profile,
    )


def test_bridge_falls_back_to_project_fetch_when_grok_package_missing(monkeypatch):
    async def missing_tool(tool_name, **kwargs):
        raise HTTPException(status_code=503, detail="grok_search is not importable: missing")

    async def fake_fallback(url):
        return {"content": "page: " + url}

    monkeypatch.setattr(bridge, "_call_grok_tool", missing_tool)
    monkeypatch.setattr(bridge, "_fallback_web_fetch", fake_fallback)

    result = asyncio.run(
        bridge._call_grok_tool_or_fallback("web_fetch", url="https://example.com/news")
    )

    assert result == {"content": "page: https://example.com/news"}
