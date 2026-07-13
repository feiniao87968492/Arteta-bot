from .. import behavior_policy
from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool


def show_behavior_policy(ctx: ToolContext) -> str:
    return behavior_policy.format_group_policies(ctx.group_id)


def update_behavior_policy(
    ctx: ToolContext,
    key: str,
    value: str = "",
    value_json: str = "",
    ttl_turns=None,
    reason: str = "",
    mode: str = "soft",
) -> str:
    parsed_value = behavior_policy.parse_policy_value(value=value, value_json=value_json)
    item = behavior_policy.set_group_policy(
        ctx.group_id,
        key,
        parsed_value,
        mode=mode,
        ttl_turns=ttl_turns,
        reason=reason,
        source="agent_tool",
    )
    ttl = " ttl={0}".format(item["ttl_turns"]) if item.get("ttl_turns") else ""
    return "已更新本群行为策略：{0}={1}{2}".format(
        item["key"],
        behavior_policy.format_policy_value(item.get("value")),
        ttl,
    )


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="show_behavior_policy",
        description="查看当前群已生效的可持久化行为策略，例如表情、回复风格、trace、渲染样式和临时工具偏好。",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=show_behavior_policy,
        permission="safe_read",
        category="behavior_policy",
        timeout_seconds=5.0,
    ))
    ensure_tool(ToolSpec(
        name="update_behavior_policy",
        description=(
            "更新当前群的可持久化行为策略。只用于软行为偏好，不用于绕过权限。"
            "例如 emoji.enabled=false、progress.enabled=true、reply.default_detail_mode=expanded、"
            "tool.send_mood_emoji.disabled=true、render.reply_body={...}。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "策略键；允许 emoji.*、progress.*、render.*、reply.*、trace.*、tool.* 这类软行为策略",
                },
                "value": {
                    "type": "string",
                    "description": "普通字符串值；布尔值可填 true/false。复杂值请用 value_json",
                },
                "value_json": {
                    "type": "string",
                    "description": "JSON 编码的策略值，例如 false 或 {\"font_scale\":5}",
                },
                "ttl_turns": {
                    "type": "integer",
                    "description": "可选：策略保留的对话轮数，最多 100；不传表示长期保留",
                },
                "reason": {
                    "type": "string",
                    "description": "为什么修改该策略，简短填写",
                },
                "mode": {
                    "type": "string",
                    "enum": ["soft", "hard"],
                    "description": "策略模式；普通行为偏好用 soft",
                    "default": "soft",
                },
            },
            "required": ["key"],
        },
        handler=update_behavior_policy,
        permission="safe_write",
        category="behavior_policy",
        timeout_seconds=5.0,
    ))
