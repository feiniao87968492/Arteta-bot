import json

from plugins.arteta_agent.context import ToolContext


def make_context(**kwargs):
    data = {
        "bot": None,
        "event": None,
        "user_id": "user-1",
        "group_id": "group-1",
        "nickname": "player",
        "raw_message": "",
        "is_group": True,
        "is_admin": False,
        "extra": {},
    }
    data.update(kwargs)
    return ToolContext(**data)


def tool_names(plan):
    return [call.name for call in plan.required_tools]


def test_plan_builder_combines_memory_preference_and_document_context():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    messages = [{"role": "user", "content": "记住以后简短回答并分析这个 PDF"}]
    ctx = make_context(extra={"document_urls": [{"url": "https://files.example/a.pdf", "name": "a.pdf"}]})

    decision = route_message(messages, ctx)
    plan = build_plan(decision, ctx)

    assert len(decision.intents) >= 2
    assert "remember_user_preference" in tool_names(plan)
    assert "read_document" in tool_names(plan)
    memory_call = next(call for call in plan.required_tools if call.name == "remember_user_preference")
    document_call = next(call for call in plan.required_tools if call.name == "read_document")
    assert "简短回答" in memory_call.arguments["memory"]
    assert document_call.arguments == {}


def test_plan_builder_combines_group_memory_and_latest_web_verification():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    messages = [{"role": "user", "content": "你之前说阿森纳会赢，现在查最新结果"}]
    ctx = make_context()

    decision = route_message(messages, ctx)
    plan = build_plan(decision, ctx)

    assert "query_group_memory" in tool_names(plan)
    assert any(name in tool_names(plan) for name in ("grok_search", "verify_recent_claim", "web_search"))


def test_plan_builder_keeps_memory_score_recall_out_of_forced_web():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    messages = [{"role": "user", "content": "塔子你还记得你昨天预测的这场比赛的比分吗"}]
    decision = route_message(messages, make_context())
    plan = build_plan(decision, make_context())

    assert "query_group_memory" in tool_names(plan)
    assert all(name not in tool_names(plan) for name in ("grok_search", "verify_recent_claim", "web_search"))


def test_routing_does_not_force_math_for_broad_numeric_phrases():
    from plugins.arteta_agent.routing.heuristic_router import route_message

    for text in ["今天几号", "这个多少钱", "1-0"]:
        decision = route_message([{"role": "user", "content": text}], make_context())
        assert "solve_math_question" not in [call.name for call in decision.required_tools]


def test_routing_forces_math_for_explicit_equation():
    from plugins.arteta_agent.routing.heuristic_router import route_message

    decision = route_message([{"role": "user", "content": "求解 x^2-1=0"}], make_context())

    required = {call.name: call for call in decision.required_tools}
    assert "solve_math_question" in required
    assert json.loads(json.dumps(required["solve_math_question"].arguments, ensure_ascii=False))["question"] == "求解 x^2-1=0"


def test_plan_builder_routes_math_questions_as_direct_required_tool():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    decision = route_message([{"role": "user", "content": "求解 x^2-1=0"}], make_context())
    plan = build_plan(decision, make_context())

    assert tool_names(plan) == ["solve_math_question"]
    assert plan.required_tools[0].arguments == {"question": "求解 x^2-1=0"}
    assert plan.constraints.get("execute_single_required_tool") is True
    assert plan.constraints.get("direct_tool_response") is True


def test_agent_loop_executes_multi_intent_memory_and_document_plan(monkeypatch):
    from plugins.arteta_agent import planner
    from plugins.arteta_agent.registry import ToolSpec, clear_registry, register_tool
    from plugins.arteta_agent.trace import new_trace

    clear_registry()
    trace = new_trace("agent_registry")
    executed = []

    async def memory_handler(ctx: ToolContext, memory: str):
        executed.append(("remember_user_preference", memory))
        return "remembered"

    async def document_handler(ctx: ToolContext, url: str = "", document_index: int = 0, max_chars: int = 4000):
        executed.append(("read_document", document_index))
        return "document text"

    register_tool(ToolSpec(
        "remember_user_preference",
        "remember",
        {"type": "object", "properties": {"memory": {"type": "string"}}, "required": ["memory"]},
        memory_handler,
        permission="safe_write",
    ))
    register_tool(ToolSpec(
        "read_document",
        "read document",
        {"type": "object", "properties": {"url": {"type": "string"}, "document_index": {"type": "integer"}, "max_chars": {"type": "integer"}}},
        document_handler,
        permission="safe_read",
    ))

    calls = []

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        calls.append(messages)
        assert messages[-1]["role"] == "tool"
        return {"role": "assistant", "content": "done"}

    monkeypatch.setattr(planner, "call_llm_with_tools", fake_call)

    result = __import__("asyncio").run(planner.run_agent_loop(
        [{"role": "user", "content": "记住以后简短回答并分析这个 PDF"}],
        make_context(extra={
            "agent_trace": trace,
            "document_urls": [{"url": "https://files.example/a.pdf", "name": "a.pdf"}],
        }),
        "model",
        "key",
        max_rounds=2,
        trace=trace,
    ))

    assert result == "done"
    assert [name for name, _value in executed] == ["remember_user_preference", "read_document"]
    assert [item["name"] for item in trace["tools"][:2]] == ["remember_user_preference", "read_document"]
    assert len(calls) == 1


def test_agent_loop_executes_multi_intent_memory_and_web_plan(monkeypatch):
    from plugins.arteta_agent import planner
    from plugins.arteta_agent.registry import ToolSpec, clear_registry, register_tool
    from plugins.arteta_agent.trace import new_trace

    clear_registry()
    trace = new_trace("agent_registry")
    executed = []

    async def memory_handler(ctx: ToolContext, query: str):
        executed.append(("query_group_memory", query))
        return "memory says old prediction"

    async def grok_handler(ctx: ToolContext, query: str, freshness: str = "recent", max_results: int = 5):
        executed.append(("grok_search", query))
        return "latest result verified"

    register_tool(ToolSpec(
        "query_group_memory",
        "query memory",
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        memory_handler,
        permission="safe_read",
    ))
    register_tool(ToolSpec(
        "grok_search",
        "research",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "freshness": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        },
        grok_handler,
        permission="safe_read",
    ))

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        assert messages[-1]["role"] == "tool"
        return {"role": "assistant", "content": "combined answer"}

    monkeypatch.setattr(planner, "call_llm_with_tools", fake_call)

    result = __import__("asyncio").run(planner.run_agent_loop(
        [{"role": "user", "content": "你之前说阿森纳会赢，现在查最新结果"}],
        make_context(extra={"agent_trace": trace}),
        "model",
        "key",
        max_rounds=2,
        trace=trace,
    ))

    assert result == "combined answer"
    assert [name for name, _value in executed] == ["query_group_memory", "grok_search"]
    assert [item["name"] for item in trace["tools"][:2]] == ["query_group_memory", "grok_search"]


def test_plan_builder_applies_public_current_fact_route_policy(tmp_path, monkeypatch):
    from plugins.arteta_agent import behavior_policy
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    policy_path = tmp_path / "behavior_policy.json"
    monkeypatch.setenv("ARTETA_AGENT_BEHAVIOR_POLICY_PATH", str(policy_path))
    monkeypatch.delenv("ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH", raising=False)
    behavior_policy.set_group_policy(
        "group-1",
        "route.public_current_fact.preferred_tool",
        "verify_recent_claim",
        reason="prefer verifier for current facts",
    )

    messages = [{"role": "user", "content": "latest Arsenal transfer news"}]
    decision = route_message(messages, make_context(group_id="group-1"))
    plan = build_plan(decision, make_context(group_id="group-1"))

    assert tool_names(plan) == ["verify_recent_claim"]
    assert plan.required_tools[0].arguments == {
        "claim": "latest Arsenal transfer news",
        "preferred_sources": "",
        "max_results": 5,
    }


def test_plan_builder_routes_recent_team_match_questions_to_grok_search():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    messages = [{"role": "user", "content": "塔子你了解西班牙和比利时最近的一场比赛吗"}]
    decision = route_message(messages, make_context())
    plan = build_plan(decision, make_context())

    assert any(intent.name == "public_current_fact" for intent in decision.intents)
    assert tool_names(plan) == ["grok_search"]
    assert plan.required_tools[0].arguments == {
        "query": "塔子你了解西班牙和比利时最近的一场比赛吗",
        "freshness": "recent",
        "max_results": 5,
    }
    assert plan.constraints.get("execute_single_required_tool") is True


def test_agent_loop_executes_single_current_fact_plan_before_legacy_forced_web(monkeypatch, tmp_path):
    from plugins.arteta_agent import behavior_policy, planner
    from plugins.arteta_agent.registry import ToolSpec, clear_registry, register_tool
    from plugins.arteta_agent.trace import new_trace

    policy_path = tmp_path / "behavior_policy.json"
    monkeypatch.setenv("ARTETA_AGENT_BEHAVIOR_POLICY_PATH", str(policy_path))
    monkeypatch.delenv("ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH", raising=False)
    behavior_policy.set_group_policy(
        "group-1",
        "route.public_current_fact.preferred_tool",
        "verify_recent_claim",
        reason="prefer verifier for current facts",
    )

    clear_registry()
    trace = new_trace("agent_registry")
    executed = []

    async def verify_handler(ctx: ToolContext, claim: str, preferred_sources: str = "", max_results: int = 5):
        executed.append(("verify_recent_claim", claim, preferred_sources, max_results))
        return "verified current fact"

    async def grok_handler(ctx: ToolContext, query: str, freshness: str = "recent", max_results: int = 5):
        raise AssertionError("route policy should choose verify_recent_claim")

    register_tool(ToolSpec(
        "verify_recent_claim",
        "verify current fact",
        {
            "type": "object",
            "properties": {
                "claim": {"type": "string"},
                "preferred_sources": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["claim"],
        },
        verify_handler,
        permission="safe_read",
    ))
    register_tool(ToolSpec(
        "grok_search",
        "research",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "freshness": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        },
        grok_handler,
        permission="safe_read",
    ))

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        assert messages[-1]["role"] == "tool"
        assert "verified current fact" in messages[-1]["content"]
        return {"role": "assistant", "content": "verified answer"}

    monkeypatch.setattr(planner, "call_llm_with_tools", fake_call)

    result = __import__("asyncio").run(planner.run_agent_loop(
        [{"role": "user", "content": "latest Arsenal transfer news"}],
        make_context(group_id="group-1", extra={"agent_trace": trace}),
        "model",
        "key",
        max_rounds=2,
        trace=trace,
    ))

    assert result == "verified answer"
    assert executed == [("verify_recent_claim", "latest Arsenal transfer news", "", 5)]
    assert trace["tools"][0]["name"] == "verify_recent_claim"


def test_plan_builder_selects_available_public_current_fact_fallback_tool(tmp_path, monkeypatch):
    from plugins.arteta_agent import behavior_policy
    from plugins.arteta_agent.planning.plan_builder import build_public_current_fact_planned_call

    policy_path = tmp_path / "behavior_policy.json"
    monkeypatch.setenv("ARTETA_AGENT_BEHAVIOR_POLICY_PATH", str(policy_path))
    monkeypatch.delenv("ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH", raising=False)
    behavior_policy.set_group_policy(
        "group-1",
        "route.public_current_fact.preferred_tool",
        "verify_recent_claim",
        reason="prefer verifier for current facts",
    )

    available = {"grok_search"}
    planned = build_public_current_fact_planned_call(
        make_context(group_id="group-1"),
        {"query": "Arsenal latest injury news", "freshness": "recent", "max_results": 4},
        disabled_tools={"verify_recent_claim"},
        is_tool_available=lambda name: name in available,
    )

    assert planned is not None
    assert planned.name == "grok_search"
    assert planned.arguments == {
        "query": "Arsenal latest injury news",
        "freshness": "recent",
        "max_results": 4,
    }


def test_plan_builder_routes_trace_requests_with_direct_response_constraint():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    decision = route_message([{"role": "user", "content": "show agent trace"}], make_context())
    plan = build_plan(decision, make_context())

    assert any(intent.name == "agent_trace" for intent in decision.intents)
    assert tool_names(plan) == ["show_agent_trace"]
    assert plan.constraints.get("direct_trace_response") is True


def test_planner_uses_structured_plan_instead_of_trace_keyword_branch():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "if wants_trace_tool(state)" not in source
    assert "def wants_trace_tool" not in source
    assert "TRACE_REQUEST_MARKERS" not in source


def test_contextual_tools_detects_ui_preference_args_for_reply_body_style():
    from plugins.arteta_agent.routing.contextual_tools import detect_ui_preference_args

    args = detect_ui_preference_args([
        {"role": "user", "content": "下次回复文字标红、加粗、放大五倍"},
    ])

    assert args == {
        "target": "reply_body",
        "color": "red",
        "bold": True,
        "font_scale": 5.0,
    }


def test_planner_no_longer_defines_ui_preference_detector():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "def detect_forced_ui_preference_args" not in source
    assert "def _extract_requested_font_scale" not in source


def test_plan_builder_routes_ui_preference_requests_as_required_tool():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    decision = route_message([
        {"role": "user", "content": "下次回复文字标红、加粗、放大五倍"},
    ], make_context())
    plan = build_plan(decision, make_context())

    assert any(intent.name == "ui_preference" for intent in decision.intents)
    assert tool_names(plan) == ["update_ui_preference"]
    assert plan.required_tools[0].arguments == {
        "target": "reply_body",
        "color": "red",
        "bold": True,
        "font_scale": 5.0,
    }
    assert plan.constraints.get("execute_single_required_tool") is True
    assert plan.constraints.get("direct_tool_response") is True


def test_planner_no_longer_has_forced_ui_preference_branch():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "forced_ui_args" not in source
    assert "update_ui_preference\") and \"update_ui_preference\" not in disabled_tools" not in source


def test_contextual_tools_detects_memory_preference_args_for_future_rules():
    from plugins.arteta_agent.routing.contextual_tools import detect_memory_preference_args

    assert detect_memory_preference_args([
        {"role": "user", "content": "以后我说开会就是提醒我看阿森纳赛程"},
    ]) == {"memory": "以后我说开会就是提醒我看阿森纳赛程"}
    assert detect_memory_preference_args([
        {"role": "user", "content": "以后在回复里，飞鸟这个名字改成深绿，颜色是006400"},
    ]) == {"memory": "以后在回复里，飞鸟这个名字改成深绿，颜色是006400"}
    assert detect_memory_preference_args([
        {"role": "user", "content": "下次阿森纳比赛几点"},
    ]) == {}


def test_plan_builder_routes_memory_preference_requests_as_direct_required_tool():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    decision = route_message([
        {"role": "user", "content": "以后我说开会就是提醒我看阿森纳赛程"},
    ], make_context())
    plan = build_plan(decision, make_context())

    assert any(intent.name == "memory_preference" for intent in decision.intents)
    assert tool_names(plan) == ["remember_user_preference"]
    assert plan.required_tools[0].arguments == {
        "memory": "以后我说开会就是提醒我看阿森纳赛程",
    }
    assert plan.constraints.get("execute_single_required_tool") is True
    assert plan.constraints.get("direct_tool_response") is True


def test_plan_builder_routes_behavior_policy_instruction_as_required_tool():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    decision = route_message([
        {"role": "user", "content": "接下来十轮不要发表情"},
    ], make_context())
    plan = build_plan(decision, make_context())

    assert any(intent.name == "behavior_policy_update" for intent in decision.intents)
    assert tool_names(plan) == ["update_behavior_policy"]
    assert plan.required_tools[0].arguments["key"] == "emoji.enabled"
    assert plan.required_tools[0].arguments["value_json"] == "false"
    assert plan.required_tools[0].arguments["ttl_turns"] == 10
    assert plan.constraints.get("execute_single_required_tool") is True
    assert plan.constraints.get("direct_tool_response") is True


def test_plan_builder_routes_tool_block_instruction_as_behavior_policy_tool():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    decision = route_message([
        {"role": "user", "content": "十轮内禁止调用send_mood_emoji这个tool"},
    ], make_context())
    plan = build_plan(decision, make_context())

    assert any(intent.name == "tool_policy_update" for intent in decision.intents)
    assert tool_names(plan) == ["update_behavior_policy"]
    assert plan.required_tools[0].arguments == {
        "key": "tool.send_mood_emoji.disabled",
        "value_json": "true",
        "ttl_turns": 10,
        "reason": "十轮内禁止调用send_mood_emoji这个tool",
    }
    assert plan.constraints.get("execute_single_required_tool") is True
    assert plan.constraints.get("direct_tool_response") is True


def test_planner_no_longer_has_forced_memory_preference_branch():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "def detect_forced_memory_args" not in source
    assert "forced_memory_args" not in source
    assert "forced-remember-user-preference" not in source


def test_plan_builder_routes_link_analysis_requests_as_required_tool():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    ctx = make_context(extra={"detected_urls": ["https://example.com/a"]})
    decision = route_message([
        {"role": "user", "content": "看看这个链接讲了什么"},
    ], ctx)
    plan = build_plan(decision, ctx)

    assert any(intent.name == "link_analysis" for intent in decision.intents)
    assert tool_names(plan) == ["analyze_links"]
    assert plan.required_tools[0].arguments == {}
    assert plan.constraints.get("execute_single_required_tool") is True
    assert plan.constraints.get("direct_tool_response") is not True


def test_routing_does_not_force_link_analysis_without_link_intent():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    ctx = make_context(extra={"detected_urls": ["https://example.com/a"]})
    decision = route_message([
        {"role": "user", "content": "阿森纳今天训练怎么样"},
    ], ctx)
    plan = build_plan(decision, ctx)

    assert "analyze_links" not in tool_names(plan)


def test_planner_no_longer_has_forced_link_analysis_branch():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "def should_force_link_analysis_tool" not in source
    assert "forced-analyze-links" not in source
    assert "if should_force_link_analysis_tool" not in source


def test_plan_builder_routes_document_attachment_as_required_tool_for_empty_text():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    ctx = make_context(extra={"document_urls": [{"url": "https://files.example/a.pdf", "name": "a.pdf"}]})
    decision = route_message([{"role": "user", "content": ""}], ctx)
    plan = build_plan(decision, ctx)

    assert any(intent.name == "document_read" for intent in decision.intents)
    assert tool_names(plan) == ["read_document"]
    assert plan.required_tools[0].arguments == {}
    assert plan.constraints.get("execute_single_required_tool") is True
    assert plan.constraints.get("direct_tool_response") is not True


def test_plan_builder_routes_detected_document_url_with_url_argument():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    ctx = make_context(extra={"detected_urls": ["https://njc-download.ftn.qq.com/ftn_handler/token123"]})
    decision = route_message([{"role": "user", "content": "分析这个 pdf"}], ctx)
    plan = build_plan(decision, ctx)

    assert tool_names(plan) == ["read_document"]
    assert plan.required_tools[0].arguments == {
        "url": "https://njc-download.ftn.qq.com/ftn_handler/token123",
    }
    assert plan.constraints.get("execute_single_required_tool") is True


def test_routing_prefers_link_analysis_over_document_for_plain_link_intent():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    ctx = make_context(extra={"detected_urls": ["https://example.com/pricing"]})
    decision = route_message([{"role": "user", "content": "分析这个链接"}], ctx)
    plan = build_plan(decision, ctx)

    assert tool_names(plan) == ["analyze_links"]


def test_planner_no_longer_has_forced_document_branch():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "def should_force_document_tool" not in source
    assert "def forced_document_tool_args" not in source
    assert "forced-read-document" not in source


def test_planner_no_longer_has_forced_web_verification_branch():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "def detect_forced_web_verification_args" not in source
    assert "forced_web_args" not in source
    assert "planned_web_call = build_public_current_fact_planned_call" not in source


def test_planner_no_longer_has_forced_science_branch():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "forced_science_tool = detect_forced_science_tool" not in source
    assert "if forced_science_tool and get_tool" not in source
    assert "forced-{0}-1\".format(forced_science_tool)" not in source


def test_planner_no_longer_owns_contextual_tool_exposure_rules():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "def detect_contextual_tool_exclusions" not in source
    assert "SCIENCE_EXPOSURE_MARKERS" not in source
    assert "FOOTBALL_INTENT_MARKERS" not in source
    assert "DOCUMENT_INTENT_CATEGORY_MARKERS" not in source
    assert "def _science_tools_allowed" not in source


def test_planner_no_longer_has_direct_behavior_or_tool_policy_update_branches():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "behavior_instruction =" not in source
    assert "parse_behavior_policy_instruction(" not in source
    assert "block_instruction =" not in source
    assert "parse_tool_block_instruction(" not in source
    assert "set_group_tool_block(" not in source
    assert "def _run_forced_tool_direct" not in source
