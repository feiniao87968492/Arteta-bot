import asyncio
import inspect
import json
import time

from .audit import record_tool_audit
from .context import ToolContext
from .pending import store_from_context
from .permissions import check_permission
from .registry import ToolArgumentError, get_tool, parse_and_validate_arguments
from .response.artifacts import legacy_artifacts_for_tool
from .result import (
    TOOL_STATUS_DISABLED,
    TOOL_STATUS_ERROR,
    TOOL_STATUS_INVALID_ARGUMENTS,
    TOOL_STATUS_OK,
    TOOL_STATUS_PERMISSION_REQUIRED,
    TOOL_STATUS_TIMEOUT,
    TOOL_STATUS_UNAVAILABLE,
    ToolResult,
)
from .tool_policy import get_disabled_tools
from .trace import record_tool


def _audit_args_from_raw(raw_arguments) -> dict:
    if isinstance(raw_arguments, dict):
        value = raw_arguments
    else:
        try:
            value = json.loads(str(raw_arguments or "{}"))
        except Exception:
            return {}
    if not isinstance(value, dict):
        return {}
    return dict((str(key), None) for key in value.keys())


def _audit_detail(
    ctx: ToolContext,
    event: str,
    permission: str,
    args: dict,
    pending_action_id: str = "",
    confirmed_action_id: str = "",
    duration_ms: int = 0,
    error_code: str = "",
) -> str:
    arg_keys = sorted([str(key) for key in (args or {}).keys()])
    detail = {
        "event": str(event or ""),
        "permission": str(permission or ""),
        "arg_keys": arg_keys,
    }
    request_id = str(getattr(ctx, "request_id", "") or "").strip()
    if request_id:
        detail["request_id"] = request_id
    safe_duration_ms = max(0, int(duration_ms or 0))
    detail["duration_ms"] = safe_duration_ms
    if error_code:
        detail["error_code"] = str(error_code)
    if pending_action_id:
        detail["pending_action_id"] = str(pending_action_id)
    if confirmed_action_id:
        detail["confirmed_action_id"] = str(confirmed_action_id)
    return json.dumps(detail, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _record_executor_audit(
    ctx: ToolContext,
    tool_name: str,
    status: str,
    event: str,
    permission: str,
    args: dict = None,
    pending_action_id: str = "",
    confirmed_action_id: str = "",
    duration_ms: int = 0,
    error_code: str = "",
) -> None:
    try:
        record_tool_audit(
            ctx,
            tool_name,
            status,
            _audit_detail(
                ctx,
                event,
                permission,
                args or {},
                pending_action_id=pending_action_id,
                confirmed_action_id=confirmed_action_id,
                duration_ms=duration_ms,
                error_code=error_code,
            ),
        )
    except Exception:
        # Audit storage must never break the tool execution path. Handler-level
        # errors are still returned as ToolResult content by the executor.
        return


def _make_result(
    trace,
    name: str,
    permission: str,
    args: dict,
    status: str,
    content: str,
    pending_action_id: str = "",
    duration_ms: int = 0,
    error_code: str = "",
) -> ToolResult:
    result = ToolResult(
        name=str(name or ""),
        permission=str(permission or ""),
        status=str(status or ""),
        content=str(content or ""),
        args=args or {},
        pending_action_id=str(pending_action_id or ""),
        artifacts=legacy_artifacts_for_tool(name, content),
        duration_ms=max(0, int(duration_ms or 0)),
        error_code=str(error_code or ""),
    )
    record_tool(trace, result.name, result.permission, result.args, result)
    return result


def _normalize_handler_tool_result(
    trace,
    name: str,
    permission: str,
    args: dict,
    handler_result: ToolResult,
    duration_ms: int,
) -> ToolResult:
    allowed_statuses = set([
        TOOL_STATUS_OK,
        TOOL_STATUS_INVALID_ARGUMENTS,
        TOOL_STATUS_PERMISSION_REQUIRED,
        TOOL_STATUS_DISABLED,
        TOOL_STATUS_TIMEOUT,
        TOOL_STATUS_ERROR,
        TOOL_STATUS_UNAVAILABLE,
    ])
    status = str(getattr(handler_result, "status", "") or TOOL_STATUS_OK)
    if status not in allowed_statuses:
        status = TOOL_STATUS_ERROR
    pending_action_id = ""
    if status == TOOL_STATUS_PERMISSION_REQUIRED and permission in ("confirm_write", "admin_action"):
        pending_action_id = str(getattr(handler_result, "pending_action_id", "") or "")
    elif status == TOOL_STATUS_PERMISSION_REQUIRED:
        status = TOOL_STATUS_ERROR

    result = ToolResult(
        name=str(name or ""),
        permission=str(permission or ""),
        status=status,
        content=str(getattr(handler_result, "content", "") or ""),
        args=args or {},
        pending_action_id=pending_action_id,
        markers=list(getattr(handler_result, "markers", None) or []),
        artifacts=list(getattr(handler_result, "artifacts", None) or []),
        duration_ms=max(0, int(duration_ms or 0)),
        error_code=str(getattr(handler_result, "error_code", "") or ""),
    )
    record_tool(trace, result.name, result.permission, result.args, result)
    return result


async def _run_tool_handler(spec, args: dict, ctx: ToolContext, trace, name: str) -> ToolResult:
    started = time.monotonic()

    def _elapsed_ms() -> int:
        return max(0, int((time.monotonic() - started) * 1000))

    async def _run():
        result = spec.handler(ctx=ctx, **args)
        if inspect.isawaitable(result):
            result = await result
        return result

    try:
        raw_result = await asyncio.wait_for(_run(), timeout=spec.timeout_seconds)
        if isinstance(raw_result, ToolResult):
            return _normalize_handler_tool_result(
                trace,
                name,
                spec.permission,
                args,
                raw_result,
                _elapsed_ms(),
            )
        content = str(raw_result)
        return _make_result(trace, name, spec.permission, args, TOOL_STATUS_OK, content, duration_ms=_elapsed_ms())
    except asyncio.TimeoutError:
        content = "[ToolTimeout] {0} execution timed out".format(name)
        return _make_result(
            trace,
            name,
            spec.permission,
            args,
            TOOL_STATUS_TIMEOUT,
            content,
            duration_ms=_elapsed_ms(),
            error_code="TimeoutError",
        )
    except Exception as exc:
        content = "[ToolError] {0} failed: {1}".format(name, exc.__class__.__name__)
        return _make_result(
            trace,
            name,
            spec.permission,
            args,
            TOOL_STATUS_ERROR,
            content,
            duration_ms=_elapsed_ms(),
            error_code=exc.__class__.__name__,
        )


async def execute_tool_call_result(tool_call: dict, ctx: ToolContext) -> ToolResult:
    # Central guardrail for agent tool calls. The LLM may request a tool, but
    # this function resolves the registered spec, validates permission, applies
    # timeout, and records a sanitized trace before returning any observation.
    trace = (getattr(ctx, "extra", {}) or {}).get("agent_trace")
    function = tool_call.get("function") or {}
    name = str(function.get("name") or "")
    spec = get_tool(name)
    if not spec:
        content = "[ToolError] \u672a\u77e5\u5de5\u5177: {0}".format(name)
        result = _make_result(trace, name, "", {}, TOOL_STATUS_ERROR, content)
        _record_executor_audit(ctx, name, result.status, "unknown_tool", "", {})
        return result

    if name in get_disabled_tools(ctx.group_id):
        content = "[ToolDisabled] tool {0} is temporarily disabled for this group.".format(name)
        result = _make_result(trace, name, spec.permission, {}, TOOL_STATUS_DISABLED, content)
        _record_executor_audit(ctx, name, result.status, "disabled_tool", spec.permission, {})
        return result

    confirmed_action_id = str((getattr(ctx, "extra", {}) or {}).get("confirmed_action_id") or "").strip()
    if confirmed_action_id:
        action = store_from_context(ctx).consume_matching_action(
            confirmed_action_id,
            ctx.user_id,
            ctx.group_id,
            spec.name,
        )
        if not action:
            content = (
                "[PermissionRequired] PendingAction {0} expired or already consumed, "
                "or does not match this user/group/tool."
            ).format(confirmed_action_id)
            result = _make_result(trace, name, spec.permission, {}, TOOL_STATUS_PERMISSION_REQUIRED, content)
            _record_executor_audit(
                ctx,
                name,
                result.status,
                "confirmation_failed",
                spec.permission,
                {},
                confirmed_action_id=confirmed_action_id,
            )
            return result
        try:
            args = parse_and_validate_arguments(spec, action.get("arguments") or {})
        except ToolArgumentError as exc:
            content = "[InvalidArguments] {0}: stored PendingAction arguments are invalid: {1}".format(name, exc)
            result = _make_result(trace, name, spec.permission, {}, TOOL_STATUS_INVALID_ARGUMENTS, content)
            _record_executor_audit(
                ctx,
                name,
                result.status,
                "stored_pending_arguments_invalid",
                spec.permission,
                {},
                confirmed_action_id=confirmed_action_id,
            )
            return result
        if spec.permission == "admin_action" and not ctx.is_admin:
            content = "[PermissionRequired] tool {0} requires administrator permission.".format(name)
            result = _make_result(trace, name, spec.permission, args, TOOL_STATUS_PERMISSION_REQUIRED, content)
            _record_executor_audit(
                ctx,
                name,
                result.status,
                "confirmed_admin_permission_denied",
                spec.permission,
                args,
                confirmed_action_id=confirmed_action_id,
                duration_ms=result.duration_ms,
                error_code=result.error_code,
            )
            return result
        result = await _run_tool_handler(spec, args, ctx, trace, name)
        _record_executor_audit(
            ctx,
            name,
            result.status,
            "confirmed_action_executed",
            spec.permission,
            args,
            confirmed_action_id=confirmed_action_id,
            duration_ms=result.duration_ms,
            error_code=result.error_code,
        )
        return result

    try:
        args = parse_and_validate_arguments(spec, function.get("arguments") or "{}")
    except ToolArgumentError as exc:
        content = "[InvalidArguments] {0}: {1}".format(name, exc)
        audit_args = _audit_args_from_raw(function.get("arguments") or "{}")
        result = _make_result(trace, name, spec.permission, {}, TOOL_STATUS_INVALID_ARGUMENTS, content)
        _record_executor_audit(ctx, name, result.status, "invalid_arguments", spec.permission, audit_args)
        return result

    # Permission checks happen before the handler runs. Confirm/admin tools
    # return a pending/denied result instead of performing side effects.
    allowed, reason = check_permission(spec, ctx, args)
    if not allowed:
        if spec.permission in ("confirm_write", "admin_action") and (
            spec.permission != "admin_action" or ctx.is_admin
        ):
            action_id = store_from_context(ctx).create_action(
                user_id=ctx.user_id,
                group_id=ctx.group_id,
                tool_name=spec.name,
                arguments=args,
            )
            content = "[PermissionRequired] {0} PendingAction: {1}".format(reason, action_id)
            result = _make_result(
                trace,
                name,
                spec.permission,
                args,
                TOOL_STATUS_PERMISSION_REQUIRED,
                content,
                pending_action_id=action_id,
            )
            _record_executor_audit(
                ctx,
                name,
                result.status,
                "pending_action_created",
                spec.permission,
                args,
                pending_action_id=action_id,
                duration_ms=result.duration_ms,
                error_code=result.error_code,
            )
            return result
        content = "[PermissionRequired] {0}".format(reason)
        result = _make_result(trace, name, spec.permission, args, TOOL_STATUS_PERMISSION_REQUIRED, content)
        _record_executor_audit(ctx, name, result.status, "permission_denied", spec.permission, args)
        return result

    result = await _run_tool_handler(spec, args, ctx, trace, name)
    if spec.permission in ("safe_write", "admin_action", "confirm_write") or result.status in (
        TOOL_STATUS_TIMEOUT,
        TOOL_STATUS_ERROR,
    ):
        _record_executor_audit(
            ctx,
            name,
            result.status,
            "tool_executed",
            spec.permission,
            args,
            duration_ms=result.duration_ms,
            error_code=result.error_code,
        )
    return result


async def execute_tool_call(tool_call: dict, ctx: ToolContext) -> str:
    return (await execute_tool_call_result(tool_call, ctx)).content
