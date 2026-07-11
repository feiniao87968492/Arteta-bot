import re


def latest_user_content(messages) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


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
