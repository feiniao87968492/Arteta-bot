"""Formatting helpers for Web access tool observations."""

from .parsers.grok import _search_result_url
from .verification import _clean_text, _source_level


def _is_grok_result(item: dict) -> bool:
    """Return whether a legacy search result mapping came from GrokSearch."""
    return isinstance(item, dict) and str(item.get("_backend") or "") == "grok"


def _format_search_results(results: list) -> str:
    """Format search results as a compact, source-oriented observation."""
    if not results:
        return "未找到可用搜索结果。"

    lines = ["搜索结果（仅用于发现线索，回答事实前应继续抓取来源页面核实）："]
    if any(_is_grok_result(item) for item in results):
        lines.insert(0, "[grok]")

    for index, item in enumerate(results, start=1):
        url = _search_result_url(item)
        title = _clean_text(item.get("title")) or "(无标题)"
        snippet = _clean_text(item.get("body") or item.get("snippet"))[:260]
        date = _clean_text(item.get("date") or item.get("published") or "")
        source_level = _source_level(url)

        lines.append("{0}. {1}".format(index, title))
        lines.append("   来源等级：{0}".format(source_level))
        if date:
            lines.append("   日期：{0}".format(date))
        lines.append("   链接：{0}".format(url))
        if snippet:
            lines.append("   摘要：{0}".format(snippet))

    return "\n".join(lines)
