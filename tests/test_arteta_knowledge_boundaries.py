from plugins.arteta_agent.context import ToolContext
from plugins.arteta_agent.tools import football


def test_football_knowledge_tool_wraps_results_with_usage_boundaries(monkeypatch):
    monkeypatch.setattr(
        football,
        "query_knowledge",
        lambda topic, max_chars=3000: "灯泡演讲：阿尔特塔用灯泡解释团队能量。",
    )

    result = football.get_football_knowledge(
        ToolContext(bot=None, event=None, user_id="u", group_id="g"),
        "灯泡演讲",
    )

    assert "【知识库素材】" in result
    assert "可选素材" in result
    assert "不要逐字复述" in result
    assert "同一故事近期已使用则跳过" in result
    assert "只在能解释用户问题时使用" in result
    assert "灯泡演讲：阿尔特塔用灯泡解释团队能量。" in result
