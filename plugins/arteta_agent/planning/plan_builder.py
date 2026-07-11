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


def _rewrite_public_current_fact_tools(decision: RouteDecision, ctx: ToolContext = None) -> list:
    has_current_fact = any(intent.name == "public_current_fact" for intent in decision.intents or [])
    if not has_current_fact:
        return list(decision.required_tools or [])

    preferred_tool = _preferred_public_current_fact_tool(ctx)
    rewritten = []
    for planned in decision.required_tools or []:
        if planned.name in PUBLIC_CURRENT_FACT_TOOLS:
            rewritten.append(PlannedToolCall(
                name=preferred_tool,
                arguments=_public_current_fact_args(preferred_tool, planned),
                reason=planned.reason,
                forced=planned.forced,
            ))
        else:
            rewritten.append(planned)
    return rewritten


def build_plan(decision: RouteDecision, ctx: ToolContext = None) -> AgentPlan:
    return AgentPlan(
        required_tools=_rewrite_public_current_fact_tools(decision, ctx),
        excluded_tools=set(decision.excluded_tools or set()),
    )
