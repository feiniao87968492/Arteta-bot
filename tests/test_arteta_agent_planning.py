from plugins.arteta_agent.context import ToolContext


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


def tool_names(plan):
    return [call.name for call in plan.required_tools]


def test_required_freshness_creates_required_web_call():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    ctx = make_context(raw_message="萨卡怎么没上")
    decision = route_message([{"role": "user", "content": "萨卡怎么没上"}], ctx)
    plan = build_plan(decision, ctx, is_tool_available=lambda _name: True)

    assert decision.freshness.mode == "required"
    assert any(intent.name == "public_current_fact" for intent in decision.intents)
    assert plan.constraints.get("current_information_required") is True
    assert plan.constraints.get("execute_single_required_tool") is True
    assert plan.constraints.get("required_current_information_tool_names") == [plan.required_tools[0].name]
    assert plan.required_tools[0].forced is True
    assert plan.required_tools[0].arguments.get("query") or plan.required_tools[0].arguments.get("claim")


def test_x_url_selects_fetch_x_post():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    url = "https://x.com/FabrizioRomano/status/123456789"
    ctx = make_context(raw_message="罗马诺这个是真的吗 {0}".format(url), extra={"detected_urls": [url]})
    decision = route_message([{"role": "user", "content": "罗马诺这个是真的吗 {0}".format(url)}], ctx)
    plan = build_plan(decision, ctx, is_tool_available=lambda _name: True)

    assert decision.freshness.mode == "required"
    assert tool_names(plan) == ["fetch_x_post"]
    assert plan.required_tools[0].arguments == {"url": url}
    assert plan.constraints.get("required_current_information_tool_names") == ["fetch_x_post"]


def test_breaking_transfer_prefers_grok_when_configured():
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.heuristic_router import route_message

    ctx = make_context(raw_message="这笔转会到底成没成")
    decision = route_message([{"role": "user", "content": "这笔转会到底成没成"}], ctx)
    plan = build_plan(decision, ctx, is_tool_available=lambda name: name == "grok_search")

    assert decision.freshness.intent == "transfer_status"
    assert tool_names(plan) == ["grok_search"]
    assert plan.required_tools[0].arguments["freshness"] == "recent"
    assert plan.required_tools[0].arguments["max_results"] == 5


def test_document_read_and_web_verification_have_explicit_dependency():
    from plugins.arteta_agent.planning.execution import initial_tool_calls_from_plan
    from plugins.arteta_agent.planning.execution import initial_tool_dependencies_from_plan
    from plugins.arteta_agent.planning.plan_builder import build_plan
    from plugins.arteta_agent.routing.models import Intent, PlannedToolCall, RouteDecision

    decision = RouteDecision(
        intents=[
            Intent("document_read", 1.0, "read supplied document"),
            Intent("public_current_fact", 0.95, "verify current claim from document"),
        ],
        required_tools=[
            PlannedToolCall("read_document", {}, "read document", forced=True),
            PlannedToolCall("web_search", {"query": "claim from document"}, "verify after document", forced=True),
        ],
        constraints={"current_information_required": True},
    )

    plan = build_plan(decision, make_context(), is_tool_available=lambda name: True)
    calls = initial_tool_calls_from_plan(plan)
    dependencies = initial_tool_dependencies_from_plan(plan, calls)

    assert tool_names(plan) == ["read_document", "grok_search"]
    assert plan.dependencies == {"grok_search": ["read_document"]}
    assert dependencies == {"planned-grok-search-2": ["planned-read-document-1"]}
