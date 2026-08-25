import asyncio

from plugins.arteta_football_intelligence.sources.base import FootballSourceRequest
from plugins.arteta_football_intelligence.sources.grok_bridge import GrokBridgeFootballSource
from plugins.arteta_football_intelligence.sources.legacy_portal import LegacyPortalFootballSource


class FakeResponse(object):
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeHttpClient(object):
    def __init__(self):
        self.posts = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if url.endswith("/web_search"):
            return FakeResponse({
                "results": [
                    {
                        "title": "Arsenal confirm Saka injury update",
                        "url": "https://www.arsenal.com/news/saka-update",
                        "snippet": "Official club update.",
                        "published_time": "2026-05-23T12:00:00Z",
                    },
                    {"content": "Grok summary without a URL must be ignored"},
                ]
            })
        if url.endswith("/web_fetch"):
            return FakeResponse({
                "title": "Arsenal confirm Saka injury update",
                "url": json["url"],
                "text": "Official club update body.",
                "published_time": "2026-05-23T12:00:00Z",
            })
        return FakeResponse({})


def test_grok_bridge_source_discovers_only_url_candidates_and_fetches_evidence():
    client = FakeHttpClient()
    source = GrokBridgeFootballSource(
        api_url="http://127.0.0.1:8799",
        api_key="secret",
        http_client=client,
    )
    request = FootballSourceRequest(
        query="Arsenal injury latest",
        event_types=["injury"],
        window_start=1779530000,
        window_end=1779540000,
        max_candidates=5,
    )

    candidates = asyncio.run(source.discover(request))
    assert len(candidates) == 1
    assert candidates[0].url == "https://www.arsenal.com/news/saka-update"
    assert candidates[0].source_key == "grok_bridge"
    assert client.posts[0]["headers"]["Authorization"] == "Bearer secret"

    evidence = asyncio.run(source.fetch_evidence(candidates[0]))
    assert evidence.body_text == "Official club update body."
    assert evidence.url == candidates[0].url


def test_legacy_portal_source_wraps_existing_html_parser():
    async def fake_fetch(_source):
        return '<a href="/a.html">阿森纳继续追逐英超冠军</a>'

    source = LegacyPortalFootballSource(
        source={
            "name": "legacy",
            "source": "新浪体育",
            "url": "https://sports.sina.com.cn/global/england/",
            "base_url": "https://sports.sina.com.cn",
            "category": "premier_league",
            "max_items": 5,
        },
        fetcher=fake_fetch,
    )

    request = FootballSourceRequest(query="Arsenal", event_types=["match_result"], window_start=0, window_end=1716400000)
    candidates = asyncio.run(source.discover(request))

    assert len(candidates) == 1
    assert candidates[0].title == "阿森纳继续追逐英超冠军"
    assert candidates[0].url == "https://sports.sina.com.cn/a.html"
    assert candidates[0].source_name == "新浪体育"
