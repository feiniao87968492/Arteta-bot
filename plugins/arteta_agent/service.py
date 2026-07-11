from dataclasses import dataclass, field
from typing import List, Optional, Set

from .context import ToolContext
from .policy.service import consume_policy_turn_if_needed, should_consume_policy_turn
from .response.composer import compose_final_response


@dataclass
class PreparedAgentRun:
    state: List[dict]
    trace: Optional[dict]
    disabled_tools: Set[str]
    consume_policy_turn: bool
    artifact_markers: List[str] = field(default_factory=list)


def prepare_agent_run(
    messages,
    ctx: ToolContext,
    trace,
    disabled_tools,
) -> PreparedAgentRun:
    state = list(messages)
    if trace is None:
        trace = (getattr(ctx, "extra", {}) or {}).get("agent_trace")
    if trace is not None:
        ctx.extra = dict(ctx.extra or {})
        ctx.extra["agent_trace"] = trace
        trace.setdefault("group_id", ctx.group_id)
    disabled = set(disabled_tools or set())
    return PreparedAgentRun(
        state=state,
        trace=trace,
        disabled_tools=disabled,
        consume_policy_turn=should_consume_policy_turn(ctx.group_id, disabled),
    )


def finish_agent_run(value: str, ctx: ToolContext, prepared: PreparedAgentRun) -> str:
    consume_policy_turn_if_needed(ctx.group_id, prepared.consume_policy_turn)
    return compose_final_response(
        value,
        artifacts=prepared.artifact_markers,
        trace=prepared.trace,
    )
