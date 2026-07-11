from typing import Tuple

from .context import ToolContext
from .registry import ToolSpec


def check_permission(spec: ToolSpec, ctx: ToolContext, args: dict) -> Tuple[bool, str]:
    # Permission levels are intentionally coarse: read/generate tools can run,
    # state-changing tools need confirmation, and admin tools require admin +
    # second confirmation.
    if spec.permission == "safe_read":
        return True, ""
    if spec.permission == "safe_write":
        return True, ""
    if spec.permission == "confirm_write":
        return False, "工具 {0} 会改变状态，需要用户确认。".format(spec.name)
    if spec.permission == "admin_action":
        if not ctx.is_admin:
            return False, "工具 {0} 需要管理员权限。".format(spec.name)
        return False, "管理员工具 {0} 需要二次确认。".format(spec.name)
    return False, "未知权限等级。"
