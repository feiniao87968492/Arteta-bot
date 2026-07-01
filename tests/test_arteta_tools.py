import asyncio
import json

from plugins import arteta_tools


def test_tools_schema_excludes_search_football_news():
    names = [tool["function"]["name"] for tool in arteta_tools.TOOLS]

    assert "search_football_news" not in names


def test_football_news_shortcuts_are_disabled(monkeypatch):
    calls = []

    async def fake_search(query, category=None, days=14):
        calls.append((query, category, days))
        return "SHOULD NOT BE USED"

    monkeypatch.setattr(arteta_tools, "_search_football_news", fake_search)

    direct = asyncio.run(arteta_tools.maybe_answer_football_news_directly("塔子 最近英超有什么新闻"))
    context = asyncio.run(arteta_tools.maybe_search_football_news_for_prompt("塔子 最近英超有什么新闻"))

    assert direct == ""
    assert context == ""
    assert calls == []


def test_execute_tool_call_rejects_disabled_football_news_tool():
    result = asyncio.run(arteta_tools.execute_tool_call({
        "function": {
            "name": "search_football_news",
            "arguments": json.dumps({"query": "英超"}, ensure_ascii=False),
        }
    }))

    assert result == "未知工具: search_football_news"


def test_run_tool_loop_retries_when_model_returns_empty_final_content(monkeypatch):
    calls = []

    async def fake_call_deepseek_tool(messages):
        calls.append(list(messages))
        if len(calls) == 1:
            return [{"role": "assistant", "content": ""}]
        return [{"role": "assistant", "content": "这是图片说明。"}]

    monkeypatch.setattr(arteta_tools, "call_deepseek_tool", fake_call_deepseek_tool)

    result = asyncio.run(arteta_tools.run_tool_loop([{"role": "user", "content": "这张图讲了什么"}]))

    assert result == "这是图片说明。"
    assert len(calls) == 2
    assert calls[1][-1] == {
        "role": "user",
        "content": "请直接给出最终回复，不要返回空内容。",
    }


def test_register_config_accepts_deepseek_model():
    arteta_tools.register_config(
        football_api_token="token",
        deepseek_api_key="deepseek-key",
        deepseek_model="deepseek-v4-pro",
        arsenal_id=57,
        has_web_search=False,
    )

    assert arteta_tools.DEEPSEEK_MODEL == "deepseek-v4-pro"
