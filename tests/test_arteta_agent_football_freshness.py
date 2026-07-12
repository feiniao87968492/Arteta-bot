import asyncio
import json

from plugins.arteta_agent.context import ToolContext
from plugins.arteta_agent.result import TOOL_STATUS_OK, TOOL_STATUS_TIMEOUT, TOOL_STATUS_UNAVAILABLE, ToolResult


WEB_TOOLS = {"grok_search", "verify_recent_claim", "web_search", "fetch_x_post", "web_fetch"}


def make_context(**kwargs):
    data = {
        "bot": None,
        "event": None,
        "user_id": "user-1",
        "group_id": "group-1",
        "nickname": "player",
        "raw_message": "",
        "reply_text": "",
        "is_group": True,
        "is_admin": False,
        "extra": {},
    }
    data.update(kwargs)
    return ToolContext(**data)


def _decision_and_plan(text, ctx=None):
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    ctx = ctx or make_context(raw_message=text)
    decision = route_message([{"role": "user", "content": text}], ctx)
    plan = build_plan(decision, ctx, is_tool_available=lambda _name: True)
    return decision, plan


def _tool_names(plan):
    return [call.name for call in plan.required_tools]


def test_implicit_current_football_questions_require_web_plan():
    examples = [
        ("萨卡怎么没上", "lineup"),
        ("阿森纳下一场打谁", "current_fixture"),
        ("这笔转会到底成没成", "transfer_status"),
        ("罗马诺又发什么了", "breaking_football_news"),
        ("赖斯最近状态怎么样", "current_player_evaluation"),
        ("阿森纳积分榜排名多少", "current_standings"),
        ("阿森纳伤病名单现在怎么样", "injury_status"),
        ("塔子你了解西班牙和比利时最近的一场比赛吗", "recent_match_result"),
    ]

    for text, expected_intent in examples:
        decision, plan = _decision_and_plan(text)

        assert decision.freshness.mode == "required", text
        assert decision.freshness.intent == expected_intent
        assert any(intent.name == "public_current_fact" for intent in decision.intents)
        assert any(name in WEB_TOOLS for name in _tool_names(plan))
        assert plan.constraints.get("current_information_required") is True
        assert plan.required_tools[0].forced is True
        assert plan.required_tools[0].arguments.get("query") or plan.required_tools[0].arguments.get("claim")


def test_stable_football_history_and_tactics_do_not_require_web():
    examples = [
        "温格为什么离开阿森纳",
        "高位逼抢为什么怕长传",
        "2006 年欧冠决赛发生了什么",
    ]

    for text in examples:
        decision, plan = _decision_and_plan(text)

        assert decision.freshness.mode == "none", text
        assert all(name not in WEB_TOOLS for name in _tool_names(plan))


def test_pronoun_question_resolves_current_football_entity_from_reply():
    ctx = make_context(
        raw_message="他怎么没上",
        reply_text="阿森纳首发出来了，萨卡不在大名单。",
    )

    decision, plan = _decision_and_plan("他怎么没上", ctx)

    assert decision.freshness.mode == "required"
    assert decision.freshness.intent == "lineup"
    assert "Bukayo Saka" in decision.freshness.resolved_entities
    assert "Bukayo Saka" in decision.freshness.query_hint
    assert any(name in WEB_TOOLS for name in _tool_names(plan))


def test_followup_question_uses_recent_football_context():
    ctx = make_context(
        raw_message="下一场呢",
        extra={
            "recent_messages": [
                {"message": "阿森纳这轮赢了热刺"},
                {"message": "萨卡状态不错"},
            ]
        },
    )

    decision, plan = _decision_and_plan("下一场呢", ctx)

    assert decision.freshness.mode == "required"
    assert decision.freshness.intent == "current_fixture"
    assert "Arsenal" in decision.freshness.resolved_entities
    assert any(name in WEB_TOOLS for name in _tool_names(plan))


def test_x_status_url_requires_fetch_x_post_plan():
    ctx = make_context(
        raw_message="罗马诺这个是真的吗 https://x.com/FabrizioRomano/status/123456789",
        extra={"detected_urls": ["https://x.com/FabrizioRomano/status/123456789"]},
    )

    decision, plan = _decision_and_plan("罗马诺这个是真的吗 https://x.com/FabrizioRomano/status/123456789", ctx)

    assert decision.freshness.mode == "required"
    assert decision.freshness.preferred_web_tools == ["fetch_x_post"]
    assert _tool_names(plan)[0] == "fetch_x_post"
    assert plan.required_tools[0].arguments == {"url": "https://x.com/FabrizioRomano/status/123456789"}


def test_required_current_information_tool_timeout_blocks_model_fallback():
    from plugins.arteta_agent.runtime.config import AgentRunConfig
    from plugins.arteta_agent.runtime.runner import AgentRuntimeRunner
    from plugins.arteta_agent.runtime.state import AgentState

    async def fake_execute(tool_call, ctx):
        return ToolResult(
            name="grok_search",
            permission="safe_read",
            status=TOOL_STATUS_TIMEOUT,
            content="[GrokSearchTimeout] search timed out",
            error_code="TimeoutError",
        )

    async def fake_model(messages, runtime_state):
        raise AssertionError("required current information failure must stop before model fallback")

    state = AgentState(
        messages=[{"role": "user", "content": "萨卡怎么没上"}],
        ctx=make_context(),
        allowed_permissions={"safe_read"},
    )
    runner = AgentRuntimeRunner(model_call=fake_model, tool_executor=fake_execute)

    result = asyncio.run(runner.run(
        state,
        AgentRunConfig(
            max_rounds=2,
            required_current_information_tool_call_ids=["planned-grok-search-1"],
        ),
        initial_tool_calls=[{
            "id": "planned-grok-search-1",
            "type": "function",
            "function": {"name": "grok_search", "arguments": json.dumps({"query": "Bukayo Saka absent Arsenal"})},
        }],
    ))

    assert result.stop_reason == "required_current_information_unavailable"
    assert "无法核实" in result.content
    assert state.required_web_failure_code == "TimeoutError"


def test_required_current_information_tool_unavailable_blocks_model_fallback():
    from plugins.arteta_agent.runtime.config import AgentRunConfig
    from plugins.arteta_agent.runtime.runner import AgentRuntimeRunner
    from plugins.arteta_agent.runtime.state import AgentState

    async def fake_execute(tool_call, ctx):
        return ToolResult(
            name="grok_search",
            permission="safe_read",
            status=TOOL_STATUS_UNAVAILABLE,
            content="no reliable source",
            error_code="NoReliableSource",
        )

    async def fake_model(messages, runtime_state):
        raise AssertionError("required current information unavailable must stop before model fallback")

    state = AgentState(
        messages=[{"role": "user", "content": "这笔转会到底成没成"}],
        ctx=make_context(),
        allowed_permissions={"safe_read"},
    )
    runner = AgentRuntimeRunner(model_call=fake_model, tool_executor=fake_execute)

    result = asyncio.run(runner.run(
        state,
        AgentRunConfig(
            max_rounds=2,
            required_current_information_tool_call_ids=["planned-grok-search-1"],
        ),
        initial_tool_calls=[{
            "id": "planned-grok-search-1",
            "type": "function",
            "function": {"name": "grok_search", "arguments": json.dumps({"query": "Arsenal transfer latest"})},
        }],
    ))

    assert result.stop_reason == "required_current_information_unavailable"
    assert "无法核实" in result.content
    assert state.required_web_failure_code == "NoReliableSource"


def test_required_current_information_empty_observation_blocks_model_fallback():
    from plugins.arteta_agent.runtime.config import AgentRunConfig
    from plugins.arteta_agent.runtime.runner import AgentRuntimeRunner
    from plugins.arteta_agent.runtime.state import AgentState

    async def fake_execute(tool_call, ctx):
        return ToolResult(
            name="web_search",
            permission="safe_read",
            status=TOOL_STATUS_OK,
            content="",
        )

    async def fake_model(messages, runtime_state):
        raise AssertionError("empty required current information must stop before model fallback")

    state = AgentState(
        messages=[{"role": "user", "content": "下一场打谁"}],
        ctx=make_context(),
        allowed_permissions={"safe_read"},
    )
    runner = AgentRuntimeRunner(model_call=fake_model, tool_executor=fake_execute)

    result = asyncio.run(runner.run(
        state,
        AgentRunConfig(
            max_rounds=2,
            required_current_information_tool_call_ids=["planned-web-search-1"],
        ),
        initial_tool_calls=[{
            "id": "planned-web-search-1",
            "type": "function",
            "function": {"name": "web_search", "arguments": json.dumps({"query": "Arsenal next match"})},
        }],
    ))

    assert result.stop_reason == "required_current_information_unavailable"
    assert "无法核实" in result.content
    assert state.required_web_failure_code == "EmptyObservation"


def test_required_current_information_tool_success_allows_model_answer():
    from plugins.arteta_agent.runtime.config import AgentRunConfig
    from plugins.arteta_agent.runtime.runner import AgentRuntimeRunner
    from plugins.arteta_agent.runtime.state import AgentState

    async def fake_execute(tool_call, ctx):
        return ToolResult(
            name="grok_search",
            permission="safe_read",
            status=TOOL_STATUS_OK,
            content="source result says Saka has a knock",
        )

    async def fake_model(messages, runtime_state):
        assert runtime_state.current_information_satisfied is True
        return {"role": "assistant", "content": "查到的来源显示萨卡有轻伤。"}

    state = AgentState(
        messages=[{"role": "user", "content": "萨卡怎么没上"}],
        ctx=make_context(),
        allowed_permissions={"safe_read"},
    )
    runner = AgentRuntimeRunner(model_call=fake_model, tool_executor=fake_execute)

    result = asyncio.run(runner.run(
        state,
        AgentRunConfig(
            max_rounds=2,
            required_current_information_tool_call_ids=["planned-grok-search-1"],
        ),
        initial_tool_calls=[{
            "id": "planned-grok-search-1",
            "type": "function",
            "function": {"name": "grok_search", "arguments": json.dumps({"query": "Bukayo Saka absent Arsenal"})},
        }],
    ))

    assert result.stop_reason == "final"
    assert result.content == "查到的来源显示萨卡有轻伤。"


def test_implicit_current_football_questions_pass_activation_candidate_gate():
    from plugins.arteta_agent.activation import is_activation_candidate

    for text in ("萨卡怎么没上", "下一场呢", "这笔转会到底成没成", "罗马诺又发什么了"):
        assert is_activation_candidate(text) is True, text


def test_unrelated_short_message_still_fails_activation_candidate_gate():
    from plugins.arteta_agent.activation import is_activation_candidate

    assert is_activation_candidate("哈哈") is False
