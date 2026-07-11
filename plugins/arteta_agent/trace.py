import re

from .ui_preferences import apply_group_style


def new_trace(mode: str) -> dict:
    return {
        "mode": str(mode),
        "rounds": 0,
        "fallback": "no",
        "round_events": [],
        "tools": [],
    }


def record_round(trace, tool_call_count: int) -> None:
    if not trace:
        return
    trace["rounds"] = int(trace.get("rounds") or 0) + 1
    trace.setdefault("round_events", []).append({
        "round": trace["rounds"],
        "tool_call_count": int(tool_call_count or 0),
    })


def set_fallback(trace, value: str) -> None:
    if trace is not None:
        trace["fallback"] = str(value)


def status_from_result(result: str) -> str:
    if result.startswith("[PermissionRequired]"):
        return "permission_required"
    if result.startswith("[ToolTimeout]"):
        return "timeout"
    if result.startswith("[ToolError]"):
        return "error"
    if result.startswith("[ToolDisabled]"):
        return "disabled"
    if result.startswith("[InvalidArguments]"):
        return "invalid_arguments"
    if result.startswith("[x-post-unavailable]"):
        return "unavailable"
    return "ok"


def pending_action_from_result(result: str) -> str:
    match = re.search(r"PendingAction:\s*([A-Za-z0-9_-]+)", result or "")
    return match.group(1) if match else ""


def markers_from_result(result: str) -> list:
    markers = []
    text = str(result or "").lstrip()
    if text.startswith("[grok]"):
        markers.append("[grok]")
    return markers


def record_tool(trace, name: str, permission: str, args, result: str) -> None:
    if not trace:
        return
    # Trace output is for live debugging only. Never store prompts, API keys,
    # raw argument values, or full tool observations in this structure.
    arg_keys = sorted([str(key) for key in (args or {}).keys()])
    status = getattr(result, "status", "") or status_from_result(str(result or ""))
    pending_action_id = getattr(result, "pending_action_id", "") or pending_action_from_result(str(result or ""))
    duration_ms = int(getattr(result, "duration_ms", 0) or 0)
    error_code = str(getattr(result, "error_code", "") or "")
    markers = list(getattr(result, "markers", None) or [])
    for marker in markers_from_result(str(result or "")):
        if marker not in markers:
            markers.append(marker)
    item = {
        "name": str(name),
        "permission": str(permission or ""),
        "status": str(status),
        "arg_keys": arg_keys,
        "pending_action_id": str(pending_action_id or ""),
        "duration_ms": duration_ms,
        "error_code": error_code,
        "markers": list(markers or []),
    }
    trace.setdefault("tools", []).append(item)


PERMISSION_LABELS = {
    "safe_read": "只读",
    "safe_write": "生成",
    "confirm_write": "需确认",
    "admin_action": "管理员",
}


STATUS_LABELS = {
    "ok": "成功",
    "permission_required": "确认中",
    "timeout": "超时",
    "error": "失败",
    "disabled": "已禁用",
    "invalid_arguments": "参数错误",
    "unavailable": "不可用",
}


def _format_tool_name(item) -> str:
    return str(item.get("name") or "unknown")


def format_trace_tool_summary(trace) -> str:
    if not trace:
        return ""
    tools = trace.get("tools") or []
    if not tools:
        return "未调用工具"
    names = []
    for item in tools:
        name = _format_tool_name(item)
        if name not in names:
            names.append(name)
    return "，".join(names)


def format_trace_block(trace) -> str:
    # This block is safe to send into a test QQ group because it is derived from
    # the sanitized trace fields recorded by record_tool().
    if not trace:
        return ""
    mode = "新 Agent" if trace.get("mode") == "agent_registry" else str(trace.get("mode") or "unknown")
    fallback = "否" if str(trace.get("fallback") or "no") == "no" else str(trace.get("fallback"))
    group_id = str(trace.get("group_id") or "")
    lines = [
        apply_group_style("【Agent 调度】", group_id, "agent_trace_title"),
        apply_group_style("调用工具：{0}".format(format_trace_tool_summary(trace)), group_id, "agent_trace_tool_label"),
        "模式：{0}｜轮次：{1}｜回退：{2}".format(mode, trace.get("rounds") or 0, fallback),
    ]
    tools = trace.get("tools") or []
    if tools:
        detail_lines = []
        for index, item in enumerate(tools, start=1):
            permission = PERMISSION_LABELS.get(item.get("permission"), item.get("permission") or "未知")
            status = STATUS_LABELS.get(item.get("status"), item.get("status") or "未知")
            arg_keys = item.get("arg_keys") or []
            args_part = "｜参数：{0}".format("，".join(arg_keys)) if arg_keys else ""
            detail_lines.append("{0}. {1}（{2}）{3}{4}".format(
                index,
                _format_tool_name(item),
                permission,
                status,
                args_part,
            ))
        lines.append(apply_group_style("明细：" + "；".join(detail_lines), group_id, "agent_trace_detail"))
    marker_values = []
    for item in tools:
        for marker in item.get("markers") or []:
            if marker not in marker_values:
                marker_values.append(marker)
    if marker_values:
        lines.append("markers:" + ",".join(marker_values))
    return "\n".join(lines)
