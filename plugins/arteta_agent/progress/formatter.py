from dataclasses import dataclass
from typing import Dict, Optional

from ..registry import get_tool
from .models import (
    PROGRESS_FINAL_SYNTHESIS_HEARTBEAT,
    PROGRESS_FINAL_SYNTHESIS_STARTED,
    PROGRESS_MODEL_ROUND_STARTED,
    PROGRESS_RUN_STARTED,
    PROGRESS_RUNTIME_STOPPED,
    PROGRESS_TOOL_BATCH_FINISHED,
    PROGRESS_TOOL_BATCH_STARTED,
    PROGRESS_TOOL_FINISHED,
    PROGRESS_WAITING_CONFIRMATION,
    AgentProgressEvent,
    ToolProgressSpec,
)


ALLOWED_ERROR_CODES = {
    "TimeoutError",
    "Unavailable",
    "InvalidArguments",
    "PermissionRequired",
    "UnsafeURL",
    "ResponseTooLarge",
    "UnsupportedContentType",
}


@dataclass(frozen=True)
class ProgressFormatterPolicy(object):
    show_tool_names: bool = True
    show_observations: bool = True
    show_duration: bool = True
    show_argument_keys: bool = False


TOOL_PROGRESS_CATALOG: Dict[str, ToolProgressSpec] = {
    "grok_search": ToolProgressSpec("实时检索服务", "检索最新新闻、官宣、记者原帖和 X/Twitter 实时线索"),
    "web_search": ToolProgressSpec("公网搜索服务", "搜索公开网页来源并筛选可继续核对的结果"),
    "web_fetch": ToolProgressSpec("网页读取服务", "读取原始页面正文、标题和发布时间"),
    "verify_recent_claim": ToolProgressSpec("近期事实核验服务", "交叉核对近期说法、来源强度和证据状态"),
    "fetch_x_post": ToolProgressSpec("X 原帖读取服务", "读取 X/Twitter 原帖、作者和发布时间"),
    "analyze_links": ToolProgressSpec("链接分析服务", "打开消息中的链接并提取页面关键信息"),
    "search_news": ToolProgressSpec("足球新闻搜索服务", "搜索足球、转会和阿森纳相关的最新公开消息"),
    "search_football_news": ToolProgressSpec("本地足球新闻库服务", "检索最近收录的联赛、欧冠和足球新闻"),
    "get_arsenal_result": ToolProgressSpec("阿森纳比赛数据服务", "获取最近比赛的对手、比分和赛事信息"),
    "get_pl_table": ToolProgressSpec("英超积分榜数据服务", "获取当前排名、积分和分差"),
    "get_arsenal_injuries": ToolProgressSpec("阿森纳伤病数据服务", "核对当前伤病名单和复出信息"),
    "get_football_knowledge": ToolProgressSpec("足球战术知识库服务", "查询战术概念、历史资料和阿尔特塔相关知识"),
    "solve_math_question": ToolProgressSpec("数学专用解题 Agent 服务", "核对题目条件并完成推导", synthesis_hint="math"),
    "solve_algorithm_problem": ToolProgressSpec("算法专用解题 Agent 服务", "分析状态设计、转移关系和时间复杂度", synthesis_hint="math"),
    "solve_code_question": ToolProgressSpec("代码专用分析 Agent 服务", "检查代码逻辑、错误原因和边界情况", synthesis_hint="math"),
    "solve_science_question": ToolProgressSpec("理科综合解题 Agent 服务", "建立计算模型并核对公式和结果", synthesis_hint="math"),
    "analyze_image": ToolProgressSpec("视觉识别 Agent 服务", "读取图片中的文字、对象和关键信息", synthesis_hint="image"),
    "read_document": ToolProgressSpec("文档阅读 Agent 服务", "读取 PDF 或 DOCX 并定位与问题相关的内容"),
    "generate_image": ToolProgressSpec("图像生成服务", "根据用户描述生成图片 artifact"),
    "render_markdown_to_image": ToolProgressSpec("Markdown 与公式渲染服务", "将公式、代码或结构化内容排版成图片"),
    "render_text_to_tactical_board": ToolProgressSpec("战术板渲染服务", "将普通文本排版成战术板风格图片"),
    "query_group_memory": ToolProgressSpec("群聊长期记忆检索服务", "按语义查找本群保存的历史对话"),
    "get_recent_group_context": ToolProgressSpec("近期群聊上下文服务", "回看最近聊天并解析指代"),
    "find_recent_messages_by_alias": ToolProgressSpec("群成员发言检索服务", "根据昵称或别名查找成员最近发言"),
    "search_daily_messages": ToolProgressSpec("每日消息记录检索服务", "查找指定日期或关键词附近的群聊消息"),
    "remember_user_preference": ToolProgressSpec("用户长期偏好记忆服务", "保存用户明确要求以后持续生效的偏好"),
    "clear_group_memory": ToolProgressSpec("群聊记忆清理服务", "准备清空群聊长期记忆，执行前等待确认"),
    "get_group_members": ToolProgressSpec("群成员数据服务", "获取近期活跃群成员名单"),
    "get_member_relations": ToolProgressSpec("群内互动关系服务", "汇总指定成员最近的互动关系"),
    "get_user_profile": ToolProgressSpec("群成员档案服务", "读取指定成员的公开群内档案和最近发言"),
    "get_current_user_profile": ToolProgressSpec("当前用户档案服务", "读取当前提问者在本群保存的档案", visibility="slow_only"),
    "generate_today_group_summary": ToolProgressSpec("今日群聊总结 Agent 服务", "汇总当天主要话题和关键事件"),
    "generate_weekly_report": ToolProgressSpec("阿森纳周报生成 Agent 服务", "根据文章资料生成结构化周报"),
    "show_behavior_policy": ToolProgressSpec("行为策略读取服务", "读取当前群已生效的软行为设置", visibility="slow_only"),
    "update_behavior_policy": ToolProgressSpec("行为策略更新服务", "更新当前群的回复偏好", visibility="slow_only"),
    "update_ui_preference": ToolProgressSpec("UI 偏好更新服务", "调整受控的字体、颜色或排版设置", visibility="slow_only"),
    "show_agent_trace": ToolProgressSpec("Agent Trace 服务", "生成本次请求的脱敏调用记录", visibility="slow_only"),
    "send_mood_emoji": ToolProgressSpec("表情发送服务", "发送匹配情绪的白名单表情", visibility="silent"),
    "send_like": ToolProgressSpec("QQ 名片赞服务", "准备发送名片赞，执行前等待确认"),
    "send_group_message": ToolProgressSpec("群消息发送服务", "准备发送群消息，执行前等待确认"),
    "mute_member": ToolProgressSpec("群成员禁言服务", "准备执行管理员禁言动作，执行前等待确认"),
    "delete_message": ToolProgressSpec("消息删除服务", "准备执行管理员删消息动作，执行前等待确认"),
    "update_config": ToolProgressSpec("配置更新服务", "准备更新运行配置，执行前等待确认"),
    "update_favor": ToolProgressSpec("信任度更新服务", "准备更新成员信任度，执行前等待确认"),
    "update_user_profile_by_llm": ToolProgressSpec("群成员档案更新服务", "准备更新成员档案，执行前等待确认"),
}


def progress_spec_for_tool(name: str) -> ToolProgressSpec:
    spec = get_tool(str(name or ""))
    progress = getattr(spec, "progress", None) if spec else None
    if progress is not None:
        return progress
    return TOOL_PROGRESS_CATALOG.get(
        str(name or ""),
        ToolProgressSpec("工具服务", "执行当前任务所需的安全操作"),
    )


def format_progress_event(
    event: AgentProgressEvent,
    policy: Optional[ProgressFormatterPolicy] = None,
) -> str:
    policy = policy or ProgressFormatterPolicy()
    kind = str(getattr(event, "kind", "") or "")
    if kind == PROGRESS_RUN_STARTED:
        return "[Agent] 正在分析请求并选择可用工具。"
    if kind == PROGRESS_MODEL_ROUND_STARTED:
        return "[Plan] 我正在根据现有信息决定下一步。"
    if kind == PROGRESS_TOOL_BATCH_STARTED:
        return _format_tool_action(event, policy)
    if kind in (PROGRESS_TOOL_FINISHED, PROGRESS_TOOL_BATCH_FINISHED):
        if not policy.show_observations:
            return ""
        return _format_tool_observation(event, policy)
    if kind == PROGRESS_WAITING_CONFIRMATION:
        return _format_confirmation(event)
    if kind == PROGRESS_FINAL_SYNTHESIS_STARTED:
        return _format_final_synthesis_started(event)
    if kind == PROGRESS_FINAL_SYNTHESIS_HEARTBEAT:
        return "[Agent] 详细回答仍在生成，我正在整理结构、论据和排版。"
    if kind == PROGRESS_RUNTIME_STOPPED:
        return "[Agent] 当前执行已停止，我会用安全方式结束这次回复。"
    return ""


def _format_tool_action(event: AgentProgressEvent, policy: ProgressFormatterPolicy) -> str:
    tools = list(getattr(event, "tools", None) or [])
    visible_tools = [
        tool for tool in tools
        if progress_spec_for_tool(tool.name).visibility != "silent"
    ]
    if not visible_tools:
        return ""
    if len(visible_tools) > 1:
        names = [tool.name for tool in visible_tools]
        if set(names) == {"get_arsenal_result", "get_pl_table", "get_arsenal_injuries"}:
            return "[Action] 我将并行调用 get_arsenal_result、get_pl_table 和 get_arsenal_injuries 服务，核对赛果、积分榜和伤病信息。"
        joined = _join_tool_names(names)
        return "[Action] 我将并行调用 {0} 服务，执行本轮所需的安全读取。".format(joined)
    tool = visible_tools[0]
    spec = progress_spec_for_tool(tool.name)
    name = tool.name if policy.show_tool_names else "当前工具"
    return "[Action] 我将调用 {0} {1}，{2}。".format(name, spec.service_type, spec.action_purpose)


def _format_tool_observation(event: AgentProgressEvent, policy: ProgressFormatterPolicy) -> str:
    tools = list(getattr(event, "tools", None) or [])
    visible_tools = [
        tool for tool in tools
        if progress_spec_for_tool(tool.name).visibility != "silent"
    ]
    if not visible_tools:
        return ""
    status = str(getattr(event, "status", "") or "ok")
    if len(visible_tools) > 1:
        success_count = int((event.metadata or {}).get("success_count", len(visible_tools)))
        failure_count = int((event.metadata or {}).get("failure_count", 0))
        return "[Observation] 并行工具调用完成：{0} 个成功，{1} 个失败，用时 {2} 秒。".format(
            success_count,
            failure_count,
            _duration_seconds(event.duration_ms),
        )
    name = visible_tools[0].name if policy.show_tool_names else "当前工具"
    duration = "（{0} 秒）".format(_duration_seconds(event.duration_ms)) if policy.show_duration else ""
    if status == "ok":
        return "[Observation] {0} 调用完成{1}，已返回可用结果。".format(name, duration)
    if status == "empty":
        return "[Observation] {0} 调用完成{1}，但没有返回可用结果。".format(name, duration)
    if status == "timeout":
        return "[Observation] {0} 调用超时{1}，未获得可用结果。".format(name, duration)
    if status == "unavailable":
        return "[Observation] {0} 当前不可用，Agent 将根据现有计划决定是否继续。".format(name)
    safe_error = _safe_error_code(event.error_code)
    return "[Observation] {0} 调用失败（{1}），未获得可用结果。".format(name, safe_error)


def _format_confirmation(event: AgentProgressEvent) -> str:
    tools = list(getattr(event, "tools", None) or [])
    name = tools[0].name if tools else "当前工具"
    permission = tools[0].permission if tools else ""
    if permission == "admin_action":
        return "[Confirmation] {0} 需要管理员权限和二次确认，当前尚未执行。".format(name)
    return "[Confirmation] {0} 需要二次确认，当前尚未执行。".format(name)


def _format_final_synthesis_started(event: AgentProgressEvent) -> str:
    metadata = event.metadata or {}
    scene = str(metadata.get("scene") or "").strip()
    if not scene:
        for tool in list(event.tools or []):
            hint = progress_spec_for_tool(tool.name).synthesis_hint
            if hint:
                scene = hint
                break
    if scene == "math":
        return "[Agent] 解题结果已经返回，我将补全方法、关键步骤、验证和最终答案。"
    if scene == "image":
        return "[Agent] 图片内容已经识别完成，我将从画面信息、背景和核心含义三个层面展开说明。"
    if scene == "news":
        return "[Agent] 工具调用已经完成，我将按消息状态、来源强度和影响分析生成完整回答。"
    if event.tools:
        return "[Agent] 工具调用已经完成，我将基于现有结果生成一份完整回答。"
    return "[Agent] 正在分析请求并组织一份完整回答。"


def _join_tool_names(names) -> str:
    values = [str(name or "") for name in names if str(name or "").strip()]
    if len(values) <= 2:
        return " 和 ".join(values)
    return "、".join(values[:-1]) + " 和 " + values[-1]


def _duration_seconds(duration_ms: int) -> str:
    return "{0:.1f}".format(max(0, int(duration_ms or 0)) / 1000.0)


def _safe_error_code(error_code: str) -> str:
    value = str(error_code or "").strip()
    return value if value in ALLOWED_ERROR_CODES else "ToolError"
