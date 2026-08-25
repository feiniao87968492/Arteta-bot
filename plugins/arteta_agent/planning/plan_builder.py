from ..context import ToolContext
from .. import behavior_policy
from plugins.arteta_football_intelligence.config import load_settings
from ..routing.models import PlannedToolCall
from ..routing.models import RouteDecision
from .models import AgentPlan


FOOTBALL_KNOWLEDGE_TOOL = "query_current_football_knowledge"
PUBLIC_CURRENT_FACT_TOOLS = ("web_search", "verify_recent_claim", "grok_search")
CURRENT_INFORMATION_TOOLS = (
    FOOTBALL_KNOWLEDGE_TOOL,
    "grok_search",
    "verify_recent_claim",
    "web_search",
    "fetch_x_post",
    "web_fetch",
)
DIRECT_TECHNICAL_TOOLS = {
    "solve_science_question",
    "solve_algorithm_problem",
    "solve_code_question",
    "solve_math_question",
}


def _preferred_public_current_fact_tool(ctx: ToolContext = None) -> str:
    group_id = str(getattr(ctx, "group_id", "") or "") if ctx is not None else ""
    item = behavior_policy.get_group_policy(group_id, "route.public_current_fact.preferred_tool")
    tool_name = str(item.get("value") or "").strip()
    if tool_name in PUBLIC_CURRENT_FACT_TOOLS:
        return tool_name
    return "web_search"


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


def _football_knowledge_first_enabled() -> bool:
    return bool(load_settings().knowledge_first_enabled)


def _knowledge_first_excluded_intent(intent: str) -> bool:
    return intent in {
        "lineup",
        "current_standings",
        "live_score",
        "current_match_event",
    }


def _event_types_for_freshness_intent(intent: str) -> list:
    mapping = {
        "injury_status": ["injury", "training"],
        "transfer_status": ["transfer", "contract"],
        "breaking_football_news": ["transfer", "injury", "club_announcement", "other"],
        "recent_match_result": ["match_result"],
        "current_fixture": ["fixture"],
        "current_player_evaluation": ["player_form"],
        "current_team_evaluation": ["player_form", "other"],
    }
    return list(mapping.get(str(intent or ""), ["other"]))


def _local_football_knowledge_call(decision: RouteDecision, args: dict) -> PlannedToolCall:
    freshness = getattr(decision, "freshness", None)
    query = str((args or {}).get("query") or (args or {}).get("claim") or getattr(freshness, "query_hint", "") or "")
    return PlannedToolCall(
        name=FOOTBALL_KNOWLEDGE_TOOL,
        arguments={
            "query": query,
            "event_types": _event_types_for_freshness_intent(str(getattr(freshness, "intent", "") or "")),
            "teams": list(getattr(freshness, "resolved_entities", []) or []),
            "players": list(getattr(freshness, "resolved_entities", []) or []),
            "competitions": [],
            "max_age_seconds": 0,
            "min_source_level": "",
            "max_results": 6,
        },
        reason="check fresh local football knowledge before web",
        forced=True,
    )


def _rewrite_public_current_fact_tools(
    decision: RouteDecision,
    ctx: ToolContext = None,
    disabled_tools=None,
    is_tool_available=None,
) -> list:
    has_current_fact = any(intent.name == "public_current_fact" for intent in decision.intents or [])
    if not has_current_fact:
        return list(decision.required_tools or [])
    freshness_intent = str(getattr(getattr(decision, "freshness", None), "intent", "") or "")
    use_knowledge_first = (
        _football_knowledge_first_enabled()
        and not _knowledge_first_excluded_intent(freshness_intent)
    )

    rewritten = []
    for planned in decision.required_tools or []:
        if planned.name in PUBLIC_CURRENT_FACT_TOOLS:
            fallback = build_public_current_fact_planned_call(
                ctx,
                planned.arguments,
                disabled_tools=disabled_tools,
                is_tool_available=is_tool_available,
            ) or planned
            if use_knowledge_first:
                rewritten.append(_local_football_knowledge_call(decision, planned.arguments))
            rewritten.append(fallback)
        else:
            rewritten.append(planned)
    return rewritten


def build_plan(
    decision: RouteDecision,
    ctx: ToolContext = None,
    disabled_tools=None,
    is_tool_available=None,
) -> AgentPlan:
    constraints = dict(decision.constraints or {})
    if any(intent.name == "public_current_fact" for intent in decision.intents or []):
        constraints["execute_single_required_tool"] = True
        constraints["current_information_required"] = bool(
            constraints.get("current_information_required")
            or getattr(getattr(decision, "freshness", None), "mode", "") == "required"
        )
    if (
        any(intent.name == "memory_preference" for intent in decision.intents or [])
        and len(decision.required_tools or []) == 1
        and decision.required_tools[0].name == "remember_user_preference"
    ):
        constraints["execute_single_required_tool"] = True
        constraints["direct_tool_response"] = True
    if (
        any(intent.name == "link_analysis" for intent in decision.intents or [])
        and len(decision.required_tools or []) == 1
        and decision.required_tools[0].name == "analyze_links"
    ):
        constraints["execute_single_required_tool"] = True
    if (
        any(intent.name == "document_read" for intent in decision.intents or [])
        and len(decision.required_tools or []) == 1
        and decision.required_tools[0].name == "read_document"
    ):
        constraints["execute_single_required_tool"] = True
    if (
        any(intent.name == "science" for intent in decision.intents or [])
        and len(decision.required_tools or []) == 1
        and decision.required_tools[0].name in DIRECT_TECHNICAL_TOOLS
    ):
        constraints["execute_single_required_tool"] = True
        constraints["direct_tool_response"] = True
    required_tools = _rewrite_public_current_fact_tools(
        decision,
        ctx,
        disabled_tools=disabled_tools,
        is_tool_available=is_tool_available,
    )
    if constraints.get("current_information_required"):
        constraints["required_current_information_tool_names"] = [
            planned.name for planned in required_tools if planned.name in CURRENT_INFORMATION_TOOLS
        ]
    if any(planned.name == FOOTBALL_KNOWLEDGE_TOOL for planned in required_tools):
        constraints["football_knowledge_first"] = True
        constraints["football_knowledge_refresh_on_miss"] = True
    dependencies = {}
    if (
        any(intent.name == "document_read" for intent in decision.intents or [])
        and any(intent.name == "public_current_fact" for intent in decision.intents or [])
        and any(planned.name == "read_document" for planned in required_tools)
    ):
        for planned in required_tools:
            if planned.name in PUBLIC_CURRENT_FACT_TOOLS:
                dependencies.setdefault(planned.name, [])
                if "read_document" not in dependencies[planned.name]:
                    dependencies[planned.name].append("read_document")
    if any(planned.name == FOOTBALL_KNOWLEDGE_TOOL for planned in required_tools):
        for planned in required_tools:
            if planned.name in PUBLIC_CURRENT_FACT_TOOLS:
                dependencies.setdefault(planned.name, [])
                if FOOTBALL_KNOWLEDGE_TOOL not in dependencies[planned.name]:
                    dependencies[planned.name].append(FOOTBALL_KNOWLEDGE_TOOL)
    return AgentPlan(
        required_tools=required_tools,
        excluded_tools=set(decision.excluded_tools or set()),
        constraints=constraints,
        dependencies=dependencies,
    )
