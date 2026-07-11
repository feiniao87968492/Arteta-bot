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

    async def fake_call(messages, model, api_key, allowed_permissions, disabled_tools=None):
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

    async def fake_call(messages, model, api_key, allowed_permissions, disabled_tools=None):
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
