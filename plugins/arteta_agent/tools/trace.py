from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool
from ..trace import format_trace_block


def show_agent_trace(ctx: ToolContext) -> str:
    # Trace is exposed as a read-only tool so testers can ask the agent to
    # reveal the current sanitized execution timeline on demand.
    trace = (ctx.extra or {}).get("agent_trace")
    block = format_trace_block(trace)
    return block or "[Agent Trace]\n当前请求还没有可展示的工具调用记录。"


def register_tools() -> None:
    # Test visualization tool: lets the agent answer "show trace" requests
    # without exposing prompts, secrets, raw args, or full tool results.
    ensure_tool(ToolSpec(
        name="show_agent_trace",
        description="展示当前请求的脱敏 Agent Trace，用于测试可视化；不会输出 prompt、密钥、完整参数或完整工具结果。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=show_agent_trace,
        permission="safe_read",
        category="debug",
        timeout_seconds=5.0,
    ))
