from ..context import ToolContext
from .. import behavior_policy
from ..routing.models import PlannedToolCall
from ..routing.models import RouteDecision
from .models import AgentPlan


PUBLIC_CURRENT_FACT_TOOLS = ("grok_search", "verify_recent_claim", "web_search")


def _preferred_public_current_fact_tool(ctx: ToolContext = None) -> str:
    group_id = str(getattr(ctx, "group_id", "") or "") if ctx is not None else ""
    item = behavior_policy.get_group_policy(group_id, "route.public_current_fact.preferred_tool")
    tool_name = str(item.get("value") or "").strip()
    if tool_name in PUBLIC_CURRENT_FACT_TOOLS:
        return tool_name
    return "grok_search"


def _public_current_fact_args(tool_name: str, planned: PlannedToolCall) -> dict:
    args = dict(planned.arguments or {})
    text = str(args.get("query") or args.get("claim") or "").strip()
    max_results = int(args.get("max_results") or 5)
    if tool_name == "verify_recent_claim":
        return {
            "claim": text,
            "preferred_sources": "",
            "max_results": max_results,
        }
    return {
        "query": text,
        "freshness": str(args.get("freshness") or "recent"),
        "max_results": max_results,
    }


def build_public_current_fact_planned_call(
    ctx: ToolContext = None,
    args: dict = None,
    disabled_tools=None,
    is_tool_available=None,
):
    disabled = set(disabled_tools or set())
    available = is_tool_available or (lambda _name: True)
    candidates = []
    preferred = _preferred_public_current_fact_tool(ctx)
    if preferred:
        candidates.append(preferred)
    for fallback in PUBLIC_CURRENT_FACT_TOOLS:
        if fallback not in candidates:
            candidates.append(fallback)

    seed = PlannedToolCall(
        name="grok_search",
        arguments=dict(args or {}),
        reason="verify current public football fact",
        forced=True,
    )
    for tool_name in candidates:
        if tool_name in disabled or not available(tool_name):
            continue
        return PlannedToolCall(
            name=tool_name,
            arguments=_public_current_fact_args(tool_name, seed),
            reason=seed.reason,
            forced=seed.forced,
        )
    return None


def _rewrite_public_current_fact_tools(decision: RouteDecision, ctx: ToolContext = None) -> list:
    has_current_fact = any(intent.name == "public_current_fact" for intent in decision.intents or [])
    if not has_current_fact:
        return list(decision.required_tools or [])

    rewritten = []
    for planned in decision.required_tools or []:
        if planned.name in PUBLIC_CURRENT_FACT_TOOLS:
            rewritten.append(build_public_current_fact_planned_call(ctx, planned.arguments) or planned)
        else:
            rewritten.append(planned)
    return rewritten


def build_plan(decision: RouteDecision, ctx: ToolContext = None) -> AgentPlan:
    return AgentPlan(
        required_tools=_rewrite_public_current_fact_tools(decision, ctx),
        excluded_tools=set(decision.excluded_tools or set()),
    )
