from ..context import ToolContext
from ..routing.models import RouteDecision
from .models import AgentPlan


def build_plan(decision: RouteDecision, ctx: ToolContext = None) -> AgentPlan:
    return AgentPlan(
        required_tools=list(decision.required_tools or []),
        excluded_tools=set(decision.excluded_tools or set()),
    )
