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

    def fail_legacy_forced_web(messages):
        raise AssertionError("single current fact should run through RouteDecision plan first")

    async def fake_call(messages, model, api_key, api_url="", allowed_permissions=None, disabled_tools=None, temperature=0.9, request_timeout=80.0):
        assert messages[-1]["role"] == "tool"
        assert "verified current fact" in messages[-1]["content"]
        return {"role": "assistant", "content": "verified answer"}

    monkeypatch.setattr(planner, "detect_forced_web_verification_args", fail_legacy_forced_web)
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
