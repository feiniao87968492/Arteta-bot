import re
from typing import Callable, Dict, List, Tuple

from .models import EmojiReactionDecision, normalize_reaction


ReactionClassifier = Callable[..., EmojiReactionDecision]


_QUOTE_RE = re.compile(r"“[^”]*”|\"[^\"]*\"|'[^']*'|‘[^’]*’")


RULES = (
    {
        "reaction": "celebration",
        "markers": ("绝杀", "赢了", "晋级", "冠军", "夺冠", "起飞", "庆祝"),
        "intensity": "high",
        "stance": "toward_event",
        "topic": "football",
        "reason": "celebration_marker",
    },
    {
        "reaction": "approval",
        "markers": ("赞同", "满意", "说得对", "执行出色", "可以", "漂亮"),
        "intensity": "medium",
        "stance": "shared_with_user",
        "topic": "general",
        "reason": "approval_marker",
    },
    {
        "reaction": "amused",
        "markers": ("笑死", "绷不住", "梗图", "节目效果", "太有活", "反转"),
        "intensity": "medium",
        "stance": "shared_with_user",
        "topic": "meme",
        "reason": "amused_marker",
    },
    {
        "reaction": "teasing",
        "markers": ("阴阳", "讽刺", "整活", "翻车", "调侃"),
        "intensity": "medium",
        "stance": "toward_event",
        "topic": "meme",
        "reason": "teasing_marker",
    },
    {
        "reaction": "surprised",
        "markers": ("爆冷", "居然", "突然", "没想到", "这也行", "太意外"),
        "intensity": "high",
        "stance": "toward_event",
        "topic": "football_news",
        "reason": "surprised_marker",
    },
    {
        "reaction": "speechless",
        "markers": ("离谱", "难绷", "又来", "无语", "这也行"),
        "intensity": "high",
        "stance": "shared_with_user",
        "topic": "general",
        "reason": "speechless_marker",
    },
    {
        "reaction": "thinking",
        "markers": ("思考", "观察", "权衡", "再看看", "不好判断"),
        "intensity": "low",
        "stance": "toward_claim",
        "topic": "general",
        "reason": "thinking_marker",
    },
    {
        "reaction": "skeptical",
        "markers": ("靠谱吗", "我不信", "不太信", "传闻", "先别信", "可靠来源", "存疑"),
        "intensity": "medium",
        "stance": "toward_claim",
        "topic": "football_news",
        "reason": "skeptical_marker",
    },
    {
        "reaction": "encouraging",
        "markers": ("别急", "能学会", "慢慢来", "慢慢拆", "做出来", "可以学会"),
        "intensity": "medium",
        "stance": "toward_user",
        "topic": "technical",
        "reason": "encouraging_marker",
    },
    {
        "reaction": "comforting",
        "markers": ("抱抱", "理解", "确实难受", "不好受", "辛苦了"),
        "intensity": "medium",
        "stance": "toward_user",
        "topic": "general",
        "reason": "comforting_marker",
    },
    {
        "reaction": "frustrated",
        "markers": ("被绝平", "裁判", "红温", "气死", "愤怒", "不满", "扳平"),
        "intensity": "high",
        "stance": "shared_with_user",
        "topic": "match",
        "reason": "frustrated_marker",
    },
    {
        "reaction": "sad",
        "markers": ("淘汰", "重伤", "赛季报销", "离队", "遗憾", "难过", "祝他恢复"),
        "intensity": "high",
        "stance": "toward_event",
        "topic": "injury",
        "reason": "sad_marker",
    },
)


NEGATION_MARKERS = ("不是", "不算", "不要", "别", "并非", "没有", "不该", "不适合")
FOOTBALL_MARKERS = ("阿森纳", "萨卡", "球员", "新援", "绝杀", "晋级", "赛季", "裁判")
TRANSFER_MARKERS = ("转会", "新援", "官宣")
INJURY_MARKERS = ("重伤", "伤病", "赛季报销", "恢复")
MEME_MARKERS = ("梗图", "节目效果", "笑死", "整活", "反转")


def _compact(text: str) -> str:
    return str(text or "").replace(" ", "").lower()


def _remove_quoted_text(text: str) -> str:
    return _QUOTE_RE.sub("", str(text or ""))


def _is_negated(text: str, start_index: int) -> bool:
    window = text[max(0, start_index - 8):start_index]
    return any(marker in window for marker in NEGATION_MARKERS)


def _iter_marker_hits(text: str, marker: str):
    start = 0
    while True:
        index = text.find(marker, start)
        if index < 0:
            return
        yield index
        start = index + max(1, len(marker))


def _score_source(text: str, weight: float) -> Tuple[Dict[str, float], Dict[str, dict], List[str]]:
    cleaned = _compact(_remove_quoted_text(text))
    scores = {}  # type: Dict[str, float]
    details = {}  # type: Dict[str, dict]
    reasons = []  # type: List[str]
    for rule in RULES:
        reaction = normalize_reaction(str(rule["reaction"]))
        for marker in rule["markers"]:
            marker_text = _compact(marker)
            for index in _iter_marker_hits(cleaned, marker_text):
                if _is_negated(cleaned, index):
                    continue
                scores[reaction] = scores.get(reaction, 0.0) + weight
                details[reaction] = rule
                reason = str(rule["reason"])
                if reason not in reasons:
                    reasons.append(reason)
    return scores, details, reasons


def _merge_scores(left: Dict[str, float], right: Dict[str, float]) -> Dict[str, float]:
    merged = dict(left)
    for key, value in right.items():
        merged[key] = merged.get(key, 0.0) + value
    return merged


def _infer_topic(text: str, fallback: str) -> str:
    compact = _compact(text)
    if any(marker in compact for marker in INJURY_MARKERS):
        return "injury"
    if any(marker in compact for marker in TRANSFER_MARKERS):
        return "transfer"
    if any(marker in compact for marker in MEME_MARKERS):
        return "meme"
    if any(marker in compact for marker in FOOTBALL_MARKERS):
        return "football"
    return fallback


def _winner(scores: Dict[str, float]) -> str:
    if not scores:
        return "none"
    ordered_reactions = [str(rule["reaction"]) for rule in RULES]
    return sorted(scores.items(), key=lambda item: (-item[1], ordered_reactions.index(item[0])))[0][0]


def classify_emoji_reaction(
    user_text: str,
    assistant_text: str,
    response_mode: str = "",
    route_hint: str = "",
    trace_tool_names=None,
) -> EmojiReactionDecision:
    user_scores, user_details, user_reasons = _score_source(user_text, 1.0)
    assistant_scores, assistant_details, assistant_reasons = _score_source(assistant_text, 1.6)
    scores = _merge_scores(user_scores, assistant_scores)
    reaction = _winner(scores)
    if reaction == "none":
        return EmojiReactionDecision(
            reaction="none",
            confidence=0.0,
            reason_codes=["low_confidence"],
        )

    score = scores.get(reaction, 0.0)
    if score < 1.0:
        return EmojiReactionDecision(
            reaction="none",
            confidence=0.4,
            reason_codes=["low_confidence"],
        )

    details = assistant_details.get(reaction) or user_details.get(reaction) or {}
    reasons = []  # type: List[str]
    for reason in user_reasons + assistant_reasons:
        if reason not in reasons:
            reasons.append(reason)
    if assistant_scores.get(reaction, 0.0) > 0:
        reasons.append("assistant_stance")
    if response_mode:
        reasons.append("response_mode:{0}".format(response_mode))
    if route_hint:
        reasons.append("route_hint:{0}".format(route_hint))
    if trace_tool_names:
        reasons.append("trace_tools_present")

    confidence = min(0.95, 0.58 + score * 0.20)
    if confidence < 0.60:
        return EmojiReactionDecision(
            reaction="none",
            confidence=confidence,
            reason_codes=["low_confidence"],
        )

    combined_text = "{0}\n{1}".format(user_text or "", assistant_text or "")
    return EmojiReactionDecision(
        reaction=reaction,
        intensity=str(details.get("intensity", "medium")),
        stance=str(details.get("stance", "shared_with_user")),
        topic=_infer_topic(combined_text, str(details.get("topic", "general"))),
        confidence=confidence,
        reason_codes=reasons,
    )
