import re

from ..registry import list_enabled_tools


SCIENCE_TOOL_CATEGORIES = {"science"}
FOOTBALL_TOOL_CATEGORIES = {"football", "football_news", "knowledge"}
GROUP_CONTEXT_TOOL_CATEGORIES = {"group", "profile", "memory", "summary"}
WEB_TOOL_CATEGORIES = {"web"}
DOCUMENT_TOOL_CATEGORIES = {"document"}
IMAGE_TOOL_CATEGORIES = {"image"}
RENDER_TOOL_CATEGORIES = {"render"}
POLICY_TOOL_CATEGORIES = {"behavior_policy", "ui", "debug"}
ACTION_TOOL_CATEGORIES = {"qq_actions"}
ADMIN_TOOL_CATEGORIES = {"admin"}

FOOTBALL_INTENT_MARKERS = (
    "arsenal",
    "premier league",
    "pl table",
    "standings",
    "score",
    "result",
    "fixture",
    "injury",
    "transfer",
    "lineup",
    "tactic",
    "阿森纳",
    "英超",
    "欧冠",
    "积分榜",
    "排名",
    "比分",
    "赛果",
    "赛程",
    "伤病",
    "转会",
    "阵容",
    "战术",
    "球员",
)
GROUP_CONTEXT_INTENT_MARKERS = (
    "群友",
    "群员",
    "更衣室",
    "好感度",
    "关系",
    "档案",
    "记忆",
    "记得",
    "历史",
    "总结今天",
    "群里聊",
)
WEB_INTENT_MARKERS = (
    "http://",
    "https://",
    "search",
    "google",
    "twitter",
    "x.com",
    "联网",
    "搜索",
    "网页",
    "链接",
    "网址",
    "查证",
    "核实",
    "来源",
)
RECENT_MATCH_MARKERS = (
    "recent match",
    "latest match",
    "last match",
    "previous match",
    "最近一场",
    "最近的一场",
    "上一场",
    "上场",
    "近期",
)
MATCH_CONTEXT_MARKERS = (
    "match",
    "game",
    "fixture",
    "比赛",
    "对阵",
    "交手",
    "踢",
)
TEAM_PAIR_MARKERS = (
    " vs ",
    " v ",
    " versus ",
    " against ",
    "和",
    "与",
    "跟",
    "对",
    "对阵",
)
DOCUMENT_INTENT_CATEGORY_MARKERS = (
    "pdf",
    "docx",
    "文档",
    "文件",
    "附件",
    "报告",
)
IMAGE_INTENT_MARKERS = (
    "图片",
    "看图",
    "截图",
    "照片",
    "画图",
    "生成图",
)
RENDER_INTENT_MARKERS = (
    "markdown",
    "html",
    "渲染",
    "卡片",
    "海报",
    "排版",
)
POLICY_INTENT_MARKERS = (
    "trace",
    "tool",
    "策略",
    "偏好",
    "调度",
    "工具",
    "表情",
)
ACTION_INTENT_MARKERS = (
    "发表情",
    "点赞",
    "赞我",
    "撤回",
    "删消息",
    "发消息",
)
ADMIN_INTENT_MARKERS = (
    "禁言",
    "踢人",
    "管理员",
    "重启",
    "配置",
)

ALGORITHM_MARKERS = (
    "leetcode",
    "算法",
    "数据结构",
    "复杂度",
    "动态规划",
    "二分",
    "两数之和",
)
CODE_MARKERS = (
    "```",
    "python",
    "javascript",
    "typescript",
    "java ",
    "c++",
    "代码",
    "报错",
    "实现一个函数",
    "写个函数",
)
SCIENCE_MARKERS = (
    "物理",
    "力学",
    "电路",
    "加速度",
    "动量",
    "电压",
)
MATH_MARKERS = (
    "数学",
    "求解",
    "证明",
    "方程",
    "求导",
    "导数",
    "极限",
    "概率",
    "矩阵",
    "不等式",
    "几何",
    "三角",
    "微积分",
)
MATH_INTENT_MARKERS = (
    "数学",
    "求解",
    "计算",
    "算一下",
    "怎么算",
    "等于",
    "多少",
    "几",
    "证明",
    "方程",
    "题",
    "题目",
    "解一下",
)
SCIENCE_EXPOSURE_MARKERS = (
    "这题",
    "题目",
    "解题",
    "答案",
    "怎么做",
    "怎么算",
) + ALGORITHM_MARKERS + CODE_MARKERS + SCIENCE_MARKERS + MATH_MARKERS + MATH_INTENT_MARKERS


def latest_user_content(messages) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def has_any_marker(text: str, markers) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in markers)


def looks_like_recent_public_match_question(text: str) -> bool:
    lowered = str(text or "").lower()
    return (
        any(marker in lowered for marker in RECENT_MATCH_MARKERS)
        and any(marker in lowered for marker in MATCH_CONTEXT_MARKERS)
        and any(marker in lowered for marker in TEAM_PAIR_MARKERS)
    )


def has_scoreline_without_technical_context(text: str) -> bool:
    if not re.search(r"(?<!\d)\d+\s*(?:-|:|比)\s*\d+(?!\d)", text or ""):
        return False
    return not any(marker in text for marker in SCIENCE_EXPOSURE_MARKERS)


def math_notation_route(text: str) -> bool:
    if re.search(r"(\\frac|\$|[∫√π∞≤≥≠]|[a-zA-Z]\s*\^|[a-zA-Z]\s*[=<>])", text):
        return True
    if re.search(r"\d+\s*[\+\*/=]\s*\d+", text):
        return any(marker in text for marker in MATH_INTENT_MARKERS)
    if re.search(r"\d+\s*-\s*\d+", text):
        return any(marker in text for marker in MATH_INTENT_MARKERS) and not has_scoreline_without_technical_context(text)
    return False


def science_route_for_text(text: str) -> str:
    if not text:
        return ""
    lower = text.lower()
    if any(marker in lower for marker in ALGORITHM_MARKERS):
        return "solve_algorithm_problem"
    if any(marker in lower for marker in CODE_MARKERS):
        return "solve_code_question"
    if any(marker in text for marker in SCIENCE_MARKERS):
        return "solve_science_question"
    if any(marker in text for marker in MATH_MARKERS) or math_notation_route(text):
        return "solve_math_question"
    return ""


def science_tools_allowed(messages) -> bool:
    text = latest_user_content(messages).strip()
    if not text:
        return False
    if science_route_for_text(text):
        return True
    if has_scoreline_without_technical_context(text):
        return False
    lower = text.lower()
    return any(marker in text for marker in SCIENCE_EXPOSURE_MARKERS) or any(marker in lower for marker in SCIENCE_EXPOSURE_MARKERS)


def detect_contextual_tool_exclusions(messages, ctx=None) -> set:
    allowed_categories = set()
    text = latest_user_content(messages).strip()

    if has_any_marker(text, FOOTBALL_INTENT_MARKERS) or looks_like_recent_public_match_question(text):
        allowed_categories.update(FOOTBALL_TOOL_CATEGORIES)
        allowed_categories.update(WEB_TOOL_CATEGORIES)
    if has_any_marker(text, GROUP_CONTEXT_INTENT_MARKERS):
        allowed_categories.update(GROUP_CONTEXT_TOOL_CATEGORIES)
    if has_any_marker(text, WEB_INTENT_MARKERS):
        allowed_categories.update(WEB_TOOL_CATEGORIES)
    if has_any_marker(text, DOCUMENT_INTENT_CATEGORY_MARKERS):
        allowed_categories.update(DOCUMENT_TOOL_CATEGORIES)
    if has_any_marker(text, IMAGE_INTENT_MARKERS):
        allowed_categories.update(IMAGE_TOOL_CATEGORIES)
    if has_any_marker(text, RENDER_INTENT_MARKERS):
        allowed_categories.update(RENDER_TOOL_CATEGORIES)
    if has_any_marker(text, POLICY_INTENT_MARKERS):
        allowed_categories.update(POLICY_TOOL_CATEGORIES)
    if has_any_marker(text, ACTION_INTENT_MARKERS):
        allowed_categories.update(ACTION_TOOL_CATEGORIES)

    if ctx is not None:
        extra = getattr(ctx, "extra", {}) or {}
        if extra.get("detected_urls"):
            allowed_categories.update(WEB_TOOL_CATEGORIES)
        if extra.get("document_urls"):
            allowed_categories.update(DOCUMENT_TOOL_CATEGORIES)
        if extra.get("image_urls") or getattr(ctx, "image_analysis", ""):
            allowed_categories.update(IMAGE_TOOL_CATEGORIES)
        if getattr(ctx, "is_admin", False) and has_any_marker(text, ADMIN_INTENT_MARKERS):
            allowed_categories.update(ADMIN_TOOL_CATEGORIES)

    if science_tools_allowed(messages):
        allowed_categories.update(SCIENCE_TOOL_CATEGORIES)

    excluded = set()
    for tool in list_enabled_tools():
        if tool.category not in allowed_categories:
            excluded.add(tool.name)
    return excluded


def detect_memory_preference_args(messages) -> dict:
    text = latest_user_content(messages).strip()
    if not text:
        return {}
    explicit = "记住" in text or "記住" in text
    future_marker = "以后" in text or "以後" in text or "下次" in text
    preference_shape = any(marker in text for marker in (
        "我说",
        "叫我",
        "你就",
        "记得",
        "記得",
        "提醒我",
        "默认",
        "優先",
        "优先",
        "不要",
        "回复",
        "回答",
        "名字",
        "颜色",
        "色值",
        "改成",
        "换成",
        "标红",
        "标蓝",
        "绿色",
        "深绿",
        "浅绿",
        "亮绿",
    ))
    if explicit or (future_marker and preference_shape):
        return {"memory": text}
    return {}


CHINESE_NUMBERS = {
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def extract_requested_font_scale(text: str, compact: str):
    match = re.search(r"(\d+(?:\.\d+)?)(?:倍|x)", compact)
    if match:
        return float(match.group(1))
    match = re.search(r"(\d+(?:\.\d+)?)%", compact)
    if match:
        return float(match.group(1)) / 100.0
    for word, value in CHINESE_NUMBERS.items():
        if "{0}倍".format(word) in text:
            return float(value)
    return None


def detect_ui_preference_args(messages) -> dict:
    text = latest_user_content(messages).strip()
    compact = text.replace(" ", "").lower()
    if not text:
        return {}

    color = ""
    if "蓝色" in text or "藍色" in text or "标蓝" in text or "blue" in compact:
        color = "blue"
    elif "红色" in text or "紅色" in text or "标红" in text or "red" in compact:
        color = "red"
    elif "默认" in text or "取消颜色" in text or "none" in compact:
        color = "none"

    bold = None
    if "取消加粗" in text or "不要加粗" in text:
        bold = False
    elif "加粗" in text or "粗体" in text or "bold" in compact:
        bold = True

    font_size = ""
    font_scale = extract_requested_font_scale(text, compact)
    if "放大" in text or "变大" in text or "大一点" in text or "large" in compact:
        if font_scale is None:
            font_size = "large"
    elif "正常大小" in text or "恢复正常" in text or "缩小" in text:
        font_size = "normal"

    if not color and bold is None and not font_size and font_scale is None:
        return {}

    args = {}
    if ("agent" in compact or "trace" in compact or "调度" in text) and (
        "调度" in text or "标题" in text or "字样" in text or "字体" in text
    ):
        args["target"] = "agent_trace_title"
    if "调用工具" in text or "工具标签" in text:
        args["target"] = "agent_trace_tool_label"
    if "明细" in text or "详情" in text:
        args["target"] = "agent_trace_detail"
    # If the user asks to style normal reply text, do not silently map it to
    # a trace-only target. This is the path for "回复文字放大五倍".
    if not args and (
        "回复" in text
        or "回答" in text
        or "文字" in text
        or "正文" in text
        or "整条" in text
        or "全局" in text
        or "渲染" in text
        or "image" in compact
        or "render" in compact
    ):
        args["target"] = "reply_body"
    if not args:
        return {}
    if color:
        args["color"] = color
    if bold is not None:
        args["bold"] = bold
    if font_size:
        args["font_size"] = font_size
    if font_scale is not None:
        args["font_scale"] = font_scale
    return args
