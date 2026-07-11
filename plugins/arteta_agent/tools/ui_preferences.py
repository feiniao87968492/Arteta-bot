from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool
from ..ui_preferences import ALLOWED_TARGETS, NAMED_COLORS, set_group_preference


def update_ui_preference(ctx: ToolContext, target: str, color: str = "", bold=None, font_size: str = "", font_scale=None) -> str:
    pref = set_group_preference(ctx.group_id, target, color=color, bold=bold, font_size=font_size, font_scale=font_scale)
    parts = ["{0}={1}".format(key, pref.get(key)) for key in sorted(pref.keys())]
    return "已更新本群 UI 偏好：{0} {1}".format(target, " ".join(parts))


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="update_ui_preference",
        description="更新当前群的受控 UI 偏好，例如把 agent trace 标题、工具标签或明细改成指定颜色、加粗或放大。",
        parameters={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": sorted(ALLOWED_TARGETS),
                    "description": "允许修改的 UI 目标",
                },
                "color": {
                    "type": "string",
                    "description": "颜色；支持 none、常见颜色名（{0}）或 #RGB/#RRGGBB".format("、".join(sorted(NAMED_COLORS.keys()))),
                },
                "bold": {
                    "type": "boolean",
                    "description": "是否加粗；不传则保留原设置",
                },
                "font_size": {
                    "type": "string",
                    "description": "字体大小；支持 normal、large、5x、500% 或数字倍率字符串",
                },
                "font_scale": {
                    "type": "number",
                    "description": "字体倍率；例如 5 表示放大五倍。不传则保留原设置",
                },
            },
            "required": ["target"],
        },
        handler=update_ui_preference,
        permission="safe_write",
        category="ui",
        timeout_seconds=5.0,
    ))
