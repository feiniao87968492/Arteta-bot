from dataclasses import dataclass, field
import re
from typing import List


@dataclass(frozen=True)
class ResponseStyleProfile(object):
    mode: str
    persona_intensity: str
    target_length: str
    allow_football_metaphor: bool = True
    allow_mood_emoji: bool = False
    prefer_image_render: bool = False
    reason_codes: List[str] = field(default_factory=list)


def _compact_text(*parts) -> str:
    return "\n".join(str(part or "") for part in parts if part).lower()


def _has_any(text: str, markers) -> bool:
    return any(marker in text for marker in markers)


_MARKDOWN_STYLE_RE = re.compile(r"(\*\*|__|`|\[/?(?:red|blue|green|bold|scale(?:=[^\]]+)?)\])")
_OPENING_SPLIT_RE = re.compile(r"[。！？!?]\s*|\n+")


def extract_opening_signature(text: str) -> str:
    body = str(text or "").strip()
    if not body:
        return ""
    first = ""
    for part in _OPENING_SPLIT_RE.split(body):
        candidate = part.strip()
        if candidate:
            first = candidate
            break
    if not first:
        first = body
    first = _MARKDOWN_STYLE_RE.sub("", first)
    first = re.sub(r"^[>\-\s#*]+", "", first)
    first = re.sub(r"\s+", " ", first).strip(" ，,。.!！?？")
    return first[:48]


def opening_has_fixed_action(text: str) -> bool:
    opening = extract_opening_signature(text)
    head = opening[:36]
    markers = (
        "拍" + "桌子",
        "敲" + "战术板",
        "摊" + "手",
        "推开" + "更衣室门",
        "站起来说",
    )
    return _has_any(head, markers)


def build_recent_opening_guard(messages, max_items: int = 5) -> str:
    seen = set()
    signatures = []
    for message in reversed(list(messages or [])):
        if (message or {}).get("role") != "assistant":
            continue
        signature = extract_opening_signature((message or {}).get("content", ""))
        if not signature or signature in seen:
            continue
        seen.add(signature)
        signatures.append(signature)
        if len(signatures) >= max_items:
            break
    if not signatures:
        return ""
    signatures.reverse()
    return (
        "最近已使用过的开场：{0}\n"
        "本次不要重复或只做同义改写，也不要使用固定动作开场。"
    ).format("；".join(signatures))


def _profile(
    mode: str,
    persona_intensity: str,
    target_length: str,
    reason_codes,
    allow_football_metaphor: bool = True,
    allow_mood_emoji: bool = False,
    prefer_image_render: bool = False,
) -> ResponseStyleProfile:
    return ResponseStyleProfile(
        mode=mode,
        persona_intensity=persona_intensity,
        target_length=target_length,
        allow_football_metaphor=allow_football_metaphor,
        allow_mood_emoji=allow_mood_emoji,
        prefer_image_render=prefer_image_render,
        reason_codes=list(reason_codes or []),
    )


def detect_response_style_profile(
    message: str,
    has_image: bool = False,
    reply_text: str = "",
    recent_context=None,
    route_hint: str = "",
    current_information_required: bool = False,
    has_document: bool = False,
    has_url: bool = False,
) -> ResponseStyleProfile:
    text = _compact_text(message, reply_text, "\n".join(recent_context or []), route_hint)
    reasons = []

    if current_information_required:
        reasons.append("current_information_required")
        return _profile("current_news", "medium", "medium", reasons)

    if route_hint in {"web_required", "x_post", "current_news"}:
        reasons.append("route_current_news")
        return _profile("current_news", "medium", "medium", reasons)

    if _has_any(text, ("trace", "调度", "调用了什么工具", "用了什么工具", "什么工具", "为什么没走", "工具过程")):
        return _profile("serious", "light", "medium", ["trace_or_debug"], allow_football_metaphor=False)

    if _has_any(text, ("隐私", "别扩散", "不要开玩笑", "链接有没有风险", "风险", "报错", "权限")):
        return _profile("serious", "light", "medium", ["serious_or_safety"], allow_football_metaphor=False)

    if _has_any(text, ("数学", "物理", "算法", "代码", "这题怎么解", "公式")):
        return _profile(
            "serious",
            "light",
            "medium",
            ["technical_or_math"],
            allow_football_metaphor=False,
            prefer_image_render=True,
        )

    meme_markers = ("这图", "图片", "梗图", "笑死", "离谱", "节目效果", "配什么文案", "怎么看")
    if has_image and (_has_any(text, meme_markers) or route_hint in {"image_meme", "memory_image"}):
        return _profile(
            "meme",
            "light",
            "short",
            ["image_meme"],
            allow_football_metaphor=False,
            allow_mood_emoji=True,
        )
    if _has_any(text, ("笑死", "梗图", "节目效果", "表情是不是在演我")):
        return _profile(
            "meme",
            "light",
            "short",
            ["meme_text"],
            allow_football_metaphor=False,
            allow_mood_emoji=True,
        )

    current_news_markers = (
        "最新",
        "伤情",
        "伤病",
        "官宣",
        "转会",
        "下一场",
        "下场",
        "积分榜",
        "最近一场",
        "什么时候",
        "靠谱吗",
        "核一下来源",
        "核实",
        "来源",
    )
    if has_url or _has_any(text, current_news_markers):
        return _profile("current_news", "medium", "medium", ["current_news_marker"])

    tactical_markers = (
        "详细",
        "展开讲",
        "拆一下",
        "结构",
        "机制",
        "战术",
        "3-2-5",
        "高位逼抢",
        "内收",
        "出球逻辑",
        "职责",
        "比较",
    )
    if _has_any(text, tactical_markers):
        return _profile(
            "tactical_deep_dive",
            "strong",
            "long",
            ["tactical_deep_dive"],
            prefer_image_render=True,
        )

    football_markers = (
        "阿森纳",
        "萨卡",
        "厄德高",
        "赖斯",
        "哈弗茨",
        "热苏斯",
        "罗杰斯",
        "马丁内利",
        "中锋",
        "阵容",
        "争冠",
    )
    if route_hint == "football_opinion" or _has_any(text, football_markers):
        return _profile("football_opinion", "medium", "medium", ["football_opinion"])

    if _has_any(text, ("表情", "庆祝")):
        return _profile("casual", "medium", "short", ["explicit_emoji"], allow_mood_emoji=True)

    if has_document:
        return _profile("serious", "light", "medium", ["document"], allow_football_metaphor=False, prefer_image_render=True)

    return _profile("casual", "light", "short", ["default_casual"])


def build_response_style_guard(profile: ResponseStyleProfile, recent_opening_guard: str = "") -> str:
    mode_titles = {
        "casual": "日常短答",
        "meme": "梗图轻互动",
        "football_opinion": "足球观点",
        "current_news": "当前消息核验",
        "tactical_deep_dive": "战术深聊",
        "serious": "严肃/调试",
    }
    title = mode_titles.get(profile.mode, "日常短答")
    lines = ["【本轮表达模式：{0}】".format(title)]

    if profile.mode == "meme":
        lines.extend([
            "- 先接住笑点，直接说最有趣的反差。",
            "- 控制在 1～3 个短段或 120 字以内。",
            "- 不要描述自己的肢体动作，不要强行上升到战术哲学。",
        ])
    elif profile.mode == "current_news":
        lines.extend([
            "- 先区分已确认事实、传闻和个人判断。",
            "- 来源不足时明确说无法核实，不用旧印象兜底。",
            "- 语气克制，不自动发表情。",
        ])
    elif profile.mode == "tactical_deep_dive":
        lines.extend([
            "- 先给结论，再分层解释机制、空间和取舍。",
            "- 可以展开成长分析，但避免空泛口号。",
            "- 需要表格、公式或长结构时可偏向图片渲染。",
        ])
    elif profile.mode == "football_opinion":
        lines.extend([
            "- 观点要明确，先说判断，再给 2～3 个理由。",
            "- 可以有教练视角，但不要机械套战术术语。",
            "- 控制在中等长度。",
        ])
    elif profile.mode == "serious":
        lines.extend([
            "- 降低角色表演强度，直接处理问题。",
            "- 不调侃隐私、权限、错误、技术或 trace 内容。",
            "- 必要时给出下一步，不自动发表情。",
        ])
    else:
        lines.extend([
            "- 直接回应当前问题。",
            "- 简单问题可以只回答 1～3 句。",
            "- 不要描述自己的肢体动作或固定动作开场。",
        ])

    if recent_opening_guard:
        lines.append(recent_opening_guard)
    lines.append("- 最近群聊上下文只用于理解指代和事实，不是写作模板；不要只模仿最近群聊上下文里的旧短回复。")
    return "\n".join(lines)
