import re

from ..audit import record_pending_confirmation_failure
from ..executor import execute_tool_call
from ..pending import store_from_context
from ..registry import get_tool
from ..trace import record_round


PENDING_ACTION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{12,}$")


def latest_user_content(messages) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def detect_pending_action_confirmation_id(messages) -> str:
    text = latest_user_content(messages).strip()
    if not text:
        return ""
    match = re.match(r"^(?:确认执行|确认|confirm|yes)\s+([A-Za-z0-9_-]{12,})$", text, flags=re.IGNORECASE)
    if not match:
        return ""
    action_id = match.group(1).strip()
    return action_id if PENDING_ACTION_ID_RE.match(action_id) else ""


async def execute_explicit_pending_action_confirmation(action_id: str, ctx, trace) -> str:
    action = store_from_context(ctx).get_action(action_id)
    if not action:
        try:
            record_pending_confirmation_failure(ctx, action_id)
        except Exception:
            pass
        return "[PermissionRequired] PendingAction {0} expired or already consumed, or does not match this user/group/tool.".format(action_id)
    tool_name = str(action.get("tool_name") or "")
    if not get_tool(tool_name):
        return "[ToolError] PendingAction {0} references unknown tool: {1}".format(action_id, tool_name)
    tool_call = {
        "id": "confirmed-pending-action-{0}".format(action_id[:12]),
        "type": "function",
        "function": {
            "name": tool_name,
            "arguments": "{}",
        },
    }
    ctx.extra = dict(ctx.extra or {})
    ctx.extra["confirmed_action_id"] = action_id
    record_round(trace, 1)
    return await execute_tool_call(tool_call, ctx)
