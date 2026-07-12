import asyncio


def test_search_parsers_normalize_redirects_and_mark_backend():
    from plugins.arteta_agent.tools.web.parsers.bing import _parse_bing_html
    from plugins.arteta_agent.tools.web.parsers.duckduckgo import _parse_duckduckgo_html
    from plugins.arteta_agent.tools.web.parsers.markdown import _parse_markdown_search_results
    from plugins.arteta_agent.tools.web.search_backends import JinaSearchBackend

    bing_html = """
    <li class="b_algo">
      <h2><a href="https://www.arsenal.com/news">Arsenal official news</a></h2>
      <p>Latest club updates.</p>
    </li>
    """
    ddg_html = """
    <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.arsenal.com%2Ffixtures">Fixtures</a>
    <a class="result__snippet">Official fixtures.</a>
    """
    markdown = "## [Transfers](https://www.arsenal.com/news/transfers)\nOfficial transfers."

    assert _parse_bing_html(bing_html, 1)[0]["href"] == "https://www.arsenal.com/news"
    assert _parse_duckduckgo_html(ddg_html, 1)[0]["href"] == "https://www.arsenal.com/fixtures"
    assert _parse_markdown_search_results(markdown, 1)[0]["title"] == "Transfers"

    async def fake_markdown(query, max_results):
        return markdown

    hits = asyncio.run(JinaSearchBackend(fake_markdown).search("Arsenal", 1, "recent", None))
    assert hits[0].backend == "jina"
    assert hits[0].url == "https://www.arsenal.com/news/transfers"


def test_run_search_backends_preserves_order_and_budget():
    from plugins.arteta_agent.tools.web.models import SearchHit
    from plugins.arteta_agent.tools.web.search_backends import TimeBudget, run_search_backends

    now = [100.0]
    calls = []
    budget = TimeBudget(4.0, now_func=lambda: now[0])

    class EmptyBackend(object):
        name = "empty"
        timeout_seconds = 10.0

        async def search(self, query, max_results, freshness, budget):
            calls.append(("empty", round(budget.remaining(), 2)))
            now[0] = 101.5
            return []

    class HitBackend(object):
        name = "hit"
        timeout_seconds = 10.0

        async def search(self, query, max_results, freshness, budget):
            calls.append(("hit", round(budget.remaining(), 2)))
            return [SearchHit("Arsenal", "https://www.arsenal.com/news", backend="hit")]

    hits = asyncio.run(run_search_backends(
        [EmptyBackend(), HitBackend()],
        query="Arsenal",
        max_results=1,
        freshness="recent",
        budget=budget,
    ))

    assert calls == [("empty", 4.0), ("hit", 2.5)]
    assert hits[0].backend == "hit"
