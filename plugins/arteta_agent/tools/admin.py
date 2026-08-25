import json

from dashboard.api.config import ENV_WHITELIST, REPO_ROOT, get_settings
from dashboard.api.services.env_service import EnvService
from dashboard.api.services.provider_config_service import provider_field_names
from dashboard.api.services.logs_service import LogsService
from dashboard.api.services.verify_service import VerifyService
from dashboard.api.services.sqlite_service import SQLiteService

from ..audit import record_tool_audit
from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool


def _settings():
    return get_settings()


def _get_verify_service(repo_root: str) -> VerifyService:
    return VerifyService(repo_root)


async def mute_member(ctx: ToolContext, user_id: str, duration: int = 600, group_id: str = "") -> str:
    if ctx.bot is None:
        return "当前没有可用 bot，无法禁言。"
    target_group = str(group_id or ctx.group_id)
    target_user = str(user_id)
    safe_duration = max(1, min(int(duration or 600), 30 * 86400))
    if hasattr(ctx.bot, "set_group_ban"):
        await ctx.bot.set_group_ban(group_id=target_group, user_id=int(target_user), duration=safe_duration)
    else:
        await ctx.bot.call_api("set_group_ban", group_id=int(target_group), user_id=int(target_user), duration=safe_duration)
    detail = "muted user {0} in group {1} for {2}s".format(target_user, target_group, safe_duration)
    record_tool_audit(ctx, "mute_member", "ok", detail)
    return "已禁言 {0} {1} 秒。".format(target_user, safe_duration)

async def delete_message(ctx: ToolContext, message_id: str) -> str:
    if ctx.bot is None:
        return "No bot is available, cannot delete message."
    target_message = str(message_id)
    await ctx.bot.call_api("delete_msg", message_id=int(target_message))
    record_tool_audit(ctx, "delete_message", "ok", "deleted message {0}".format(target_message))
    return "Deleted message {0}.".format(target_message)


def read_logs(ctx: ToolContext, name: str = "arteta_bot.log", limit: int = 100) -> str:
    logs_dir = (ctx.extra or {}).get("logs_dir") or _settings().logs_dir
    lines = LogsService(str(logs_dir)).tail(str(name), limit=max(1, min(int(limit or 100), 500)))
    detail = "read log {0} ({1} lines)".format(name, len(lines))
    record_tool_audit(ctx, "read_logs", "ok", detail)
    if not lines:
        return "日志为空或不存在。"
    return "\n".join(lines)


def run_verify_suite(ctx: ToolContext, suite: str = "agent_registry", cases=None, online: bool = False, allow_side_effects: bool = False) -> str:
    repo_root = str((ctx.extra or {}).get("repo_root") or REPO_ROOT)
    case_list = cases if isinstance(cases, list) else []
    run_id = _get_verify_service(repo_root).start_run([str(suite or "agent_registry")], case_list, bool(online), bool(allow_side_effects))
    detail = "started verify run {0} suite={1}".format(run_id, suite)
    record_tool_audit(ctx, "run_verify_suite", "ok", detail)
    return "已启动验证任务：{0}".format(run_id)


def check_config(ctx: ToolContext) -> str:
    env_file = str((ctx.extra or {}).get("env_file") or _settings().env_file)
    items = EnvService(env_file, ENV_WHITELIST).list_masked()
    record_tool_audit(ctx, "check_config", "ok", "checked config {0}".format(env_file))
    return json.dumps(items, ensure_ascii=False, indent=2)


def update_config(ctx: ToolContext, name: str, value: str) -> str:
    if str(name) in provider_field_names():
        record_tool_audit(ctx, "update_config", "rejected", "provider group field {0}".format(name))
        return "This setting belongs to a provider group and must be verified and applied from Dashboard Config."
    env_file = str((ctx.extra or {}).get("env_file") or _settings().env_file)
    EnvService(env_file, ENV_WHITELIST).update(str(name), str(value))
    record_tool_audit(ctx, "update_config", "ok", "updated config {0}".format(name))
    return "已更新配置 {0}。".format(name)


def update_favor(ctx: ToolContext, user_id: str, favor: int = None, delta: int = None, group_id: str = "", nickname: str = "") -> str:
    target_group = str(group_id or ctx.group_id)
    target_user = str(user_id).strip()
    if not target_user:
        return "user_id 不能为空。"
    if (favor is None) == (delta is None):
        return "必须且只能提供 favor 或 delta 其中一个。"
    if delta is not None and int(delta) == 0:
        return "delta 不能为 0。"
    service = SQLiteService(_settings().db_path)
    result = service.update_user_favor(
        target_group,
        target_user,
        favor=int(favor) if favor is not None else None,
        delta=int(delta) if delta is not None else None,
        nickname=str(nickname).strip() or None,
    )
    favor_value = int(result.get("favorability", 0) or 0)
    level = str(result.get("level", ""))
    action = "favor.set" if favor is not None else "favor.delta"
    detail = "{0} {1} favor={2} level={3}".format(
        target_group,
        target_user,
        favor_value,
        level,
    )
    record_tool_audit(ctx, action, "ok", detail)
    return "已更新 {0} 在群 {1} 的好感度：{2}，当前定位：{3}。".format(target_user, target_group, favor_value, level)


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="mute_member",
        description="禁言指定群成员。管理员工具，必须管理员且二次确认后执行，并写入 audit log。",
        parameters={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "目标 QQ 号"},
                "duration": {"type": "integer", "description": "禁言秒数", "default": 600},
                "group_id": {"type": "string", "description": "目标群号，默认当前群"},
            },
            "required": ["user_id"],
        },
        handler=mute_member,
        permission="admin_action",
        category="admin",
        timeout_seconds=20.0,
    ))
    ensure_tool(ToolSpec(
        name="delete_message",
        description="Delete a QQ message by id. Admin-only and audited.",
        parameters={
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Message id to delete"},
            },
            "required": ["message_id"],
        },
        handler=delete_message,
        permission="admin_action",
        category="admin",
        timeout_seconds=20.0,
    ))
    ensure_tool(ToolSpec(
        name="read_logs",
        description="读取允许范围内的 bot/dashboard 日志尾部。管理员工具。",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "日志文件名"},
                "limit": {"type": "integer", "description": "返回末尾多少行", "default": 100},
            },
            "required": [],
        },
        handler=read_logs,
        permission="admin_action",
        category="admin",
        timeout_seconds=10.0,
    ))
    ensure_tool(ToolSpec(
        name="run_verify_suite",
        description="启动 tools/verify_features.py 验证任务。管理员工具。",
        parameters={
            "type": "object",
            "properties": {
                "suite": {"type": "string", "description": "验证 suite"},
                "cases": {"type": "array", "items": {"type": "string"}, "description": "可选 case 列表"},
                "online": {"type": "boolean", "description": "是否允许 online checks", "default": False},
                "allow_side_effects": {"type": "boolean", "description": "是否允许副作用验证", "default": False},
            },
            "required": [],
        },
        handler=run_verify_suite,
        permission="admin_action",
        category="admin",
        timeout_seconds=10.0,
    ))
    ensure_tool(ToolSpec(
        name="check_config",
        description="读取白名单配置的脱敏状态。管理员工具。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=check_config,
        permission="admin_action",
        category="admin",
        timeout_seconds=10.0,
    ))
    ensure_tool(ToolSpec(
        name="update_config",
        description="更新白名单配置项。管理员工具，必须二次确认后执行，并写入 audit log。",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "配置项名称"},
                "value": {"type": "string", "description": "新值"},
            },
            "required": ["name", "value"],
        },
        handler=update_config,
        permission="admin_action",
        category="admin",
        timeout_seconds=10.0,
    ))
    ensure_tool(ToolSpec(
        name="update_favor",
        description=(
            "修改群成员好感度。管理员工具，必须管理员且二次确认后执行，并写入 audit log。"
            "支持直接设定 favor，或用 delta 做增减。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "目标 QQ 号"},
                "group_id": {"type": "string", "description": "目标群号，默认当前群"},
                "nickname": {"type": "string", "description": "可选：目标昵称，默认当前昵称"},
                "favor": {"type": "integer", "description": "直接设定好感度"},
                "delta": {"type": "integer", "description": "增减好感度，不能为 0"},
            },
            "required": ["user_id"],
        },
        handler=update_favor,
        permission="admin_action",
        category="admin",
        timeout_seconds=20.0,
    ))
