import re
from typing import Iterable, List, Optional

from ..context import ToolContext
from .models import ConversationEntities, FreshnessDecision, Intent


RELATIVE_TIME_MARKERS = (
    "今天",
    "今晚",
    "昨天",
    "昨晚",
    "刚才",
    "刚刚",
    "现在",
    "目前",
    "最近",
    "这轮",
    "本轮",
    "这场",
    "下一场",
    "赛前",
    "赛后",
    "这赛季",
    "本赛季",
    "today",
    "tonight",
    "yesterday",
    "now",
    "currently",
    "recently",
    "this match",
    "next match",
    "this season",
    "latest",
    "recent",
    "last match",
    "previous match",
)

CURRENT_FACT_MARKERS = (
    "比分",
    "首发",
    "替补",
    "换人",
    "进球",
    "助攻",
    "红牌",
    "黄牌",
    "伤病",
    "受伤",
    "复出",
    "停赛",
    "转会",
    "续约",
    "解约",
    "官宣",
    "发布会",
    "赛程",
    "积分榜",
    "排名",
    "大名单",
    "名单",
    "状态",
    "没上",
    "不上",
    "缺席",
    "下一场",
    "上场",
    "最近一场",
    "最近的一场",
    "上一场",
    "结果",
    "赛果",
    "transfer",
    "injury",
    "fixture",
    "lineup",
    "standings",
    "score",
    "result",
)

NEWS_OR_X_MARKERS = (
    "罗马诺",
    "记者",
    "爆料",
    "消息",
    "原帖",
    "推特",
    "官推",
    "俱乐部官网",
    "发布会",
    "官宣",
    "fabrizio",
    "romano",
    "twitter",
    "x.com",
    "official",
    "news",
    "source",
)

STABLE_HISTORY_MARKERS = (
    "当年",
    "历史上",
    "曾经",
    "为什么离开",
    "职业生涯",
    "温格时代",
    "规则",
    "战术原理",
)

STABLE_TACTIC_MARKERS = (
    "高位逼抢",
    "为什么怕",
    "长传",
    "战术原理",
    "规则",
    "术语",
    "原理",
)

FOOTBALL_MARKERS = (
    "阿森纳",
    "英超",
    "欧冠",
    "西甲",
    "比利时",
    "西班牙",
    "罗马诺",
    "球队",
    "球员",
    "比赛",
    "转会",
    "伤病",
    "赛程",
    "积分榜",
    "首发",
    "arsenal",
    "football",
    "premier league",
    "champions league",
    "match",
    "fixture",
    "transfer",
    "injury",
)

PRONOUN_OR_FOLLOWUP_MARKERS = (
    "他",
    "这场",
    "这个",
    "这笔",
    "又",
    "怎么了",
    "呢",
    "真的假的",
    "谁进的",
)

PLAYER_ALIASES = {
    "萨卡": "Bukayo Saka",
    "saka": "Bukayo Saka",
    "赖斯": "Declan Rice",
    "rice": "Declan Rice",
    "厄德高": "Martin Odegaard",
    "odegaard": "Martin Odegaard",
    "哈弗茨": "Kai Havertz",
    "havertz": "Kai Havertz",
    "热苏斯": "Gabriel Jesus",
    "jesus": "Gabriel Jesus",
    "马丁内利": "Gabriel Martinelli",
    "martinelli": "Gabriel Martinelli",
}

TEAM_ALIASES = {
    "阿森纳": "Arsenal",
    "arsenal": "Arsenal",
    "枪手": "Arsenal",
    "西班牙": "Spain",
    "spain": "Spain",
    "比利时": "Belgium",
    "belgium": "Belgium",
    "热刺": "Tottenham",
    "tottenham": "Tottenham",
    "曼城": "Manchester City",
    "利物浦": "Liverpool",
    "切尔西": "Chelsea",
}


def _has_any(text: str, markers: Iterable[str]) -> bool:
    lowered = str(text or "").lower()
    return any(str(marker).lower() in lowered for marker in markers)


def _extract_x_status_url(text: str, urls: Optional[List[str]] = None) -> str:
    candidates = list(urls or [])
    candidates.extend(re.findall(r"https?://[^\s)）]+", str(text or "")))
    for url in candidates:
        if re.search(r"https?://(?:www\.)?(?:x|twitter)\.com/[^/\s]+/status/\d+", str(url), flags=re.I):
            return str(url)
    return ""


def _extract_recent_messages(ctx: ToolContext = None) -> List[str]:
    if ctx is None:
        return []
    extra = getattr(ctx, "extra", {}) or {}
    raw_recent = extra.get("recent_messages") or []
    if isinstance(raw_recent, str):
        return [line.strip() for line in raw_recent.splitlines() if line.strip()][:8]
    result = []
    for item in list(raw_recent or [])[:8]:
        if isinstance(item, dict):
            value = item.get("message") or item.get("content") or item.get("text") or ""
        else:
            value = item
        value = str(value or "").strip()
        if value:
            result.append(value)
    return result


def _collect_entities(texts: List[str], source_urls: List[str]) -> ConversationEntities:
    combined = "\n".join(texts)
    players = []
    teams = []
    for alias, canonical in PLAYER_ALIASES.items():
        if alias.lower() in combined.lower() and canonical not in players:
            players.append(canonical)
    for alias, canonical in TEAM_ALIASES.items():
        if alias.lower() in combined.lower() and canonical not in teams:
            teams.append(canonical)
    return ConversationEntities(
        players=players,
        teams=teams,
        replied_message=texts[1] if len(texts) > 1 else "",
        source_urls=list(source_urls or []),
    )


def _historical_or_stable(text: str) -> bool:
    if re.search(r"(?:19|20)\d{2}\s*年", text or "") and not _has_any(text, ("最近", "最新", "现在", "目前", "下一场")):
        return True
    if _has_any(text, STABLE_HISTORY_MARKERS):
        return True
    if _has_any(text, STABLE_TACTIC_MARKERS) and not _has_any(text, RELATIVE_TIME_MARKERS):
        return True
    return False


def _intent_for_current_text(text: str, context_text: str) -> str:
    combined = "{0}\n{1}".format(text or "", context_text or "")
    lowered = combined.lower()
    if _has_any(combined, ("伤病", "受伤", "复出", "停赛")):
        return "injury_status"
    if _has_any(combined, ("首发", "大名单", "名单", "没上", "不上", "缺席")):
        return "lineup"
    if _has_any(combined, ("转会", "续约", "解约", "成没成", "签约")):
        return "transfer_status"
    if _extract_x_status_url(combined) or _has_any(combined, NEWS_OR_X_MARKERS):
        return "breaking_football_news"
    if _has_any(combined, ("下一场", "赛程", "打谁", "对谁", "next match", "fixture")):
        return "current_fixture"
    if _has_any(combined, ("积分榜", "排名", "standings", "table")):
        return "current_standings"
    if _has_any(combined, ("最近状态", "状态怎么样", "状态如何", "recent form")):
        return "current_player_evaluation"
    if _has_any(combined, ("上一场", "最近一场", "最近的一场", "比分", "赛果", "谁进", "result", "score")):
        return "recent_match_result"
    if "recent match" in lowered or "latest match" in lowered:
        return "recent_match_result"
    return "current_team_evaluation"


def _query_hint(text: str, intent: str, entities: ConversationEntities) -> str:
    raw_text = str(text or "").strip()
    if raw_text and raw_text.isascii():
        return raw_text
    needs_context_expansion = _has_any(raw_text, PRONOUN_OR_FOLLOWUP_MARKERS)
    parts = []
    if needs_context_expansion:
        parts.extend(entities.players)
        parts.extend(entities.teams)
    if not parts and _has_any(text, ("阿森纳", "枪手")):
        parts.append("Arsenal")
    parts.append(raw_text)
    if intent == "lineup":
        parts.append("why absent lineup injury latest")
    elif intent == "current_fixture":
        parts.append("next match fixture")
    elif intent == "transfer_status":
        parts.append("transfer latest official Romano")
    elif intent == "breaking_football_news":
        parts.append("latest football news X official")
    elif intent == "current_standings":
        parts.append("standings table latest")
    elif intent == "current_player_evaluation":
        parts.append("recent form latest performance")
    elif intent == "recent_match_result":
        parts.append("latest match result scorers")
    return " ".join([item for item in parts if item]).strip()


def detect_football_freshness(
    message: str,
    intents: List[Intent],
    ctx: ToolContext = None,
) -> FreshnessDecision:
    text = str(message or "").strip()
    reply_text = str(getattr(ctx, "reply_text", "") or "") if ctx is not None else ""
    recent_messages = _extract_recent_messages(ctx)
    extra = getattr(ctx, "extra", {}) or {} if ctx is not None else {}
    source_urls = list(extra.get("detected_urls") or [])
    x_url = _extract_x_status_url(text, source_urls)
    context_text = "\n".join([reply_text] + recent_messages)
    entities = _collect_entities([text, reply_text] + recent_messages, source_urls)

    if x_url:
        return FreshnessDecision(
            mode="required",
            domain="football",
            intent="breaking_football_news",
            confidence=0.98,
            freshness_window="day",
            preferred_web_tools=["fetch_x_post"],
            reason_codes=["x_status_url", "current_source"],
            resolved_entities=entities.players + entities.teams,
            query_hint=x_url,
        )

    if not text:
        return FreshnessDecision()

    if _historical_or_stable(text):
        return FreshnessDecision(
            mode="none",
            domain="football" if _has_any(text, FOOTBALL_MARKERS) else "",
            intent="stable_football_knowledge",
            confidence=0.9,
            reason_codes=["stable_or_historical"],
            resolved_entities=entities.players + entities.teams,
        )

    combined = "{0}\n{1}".format(text, context_text)
    has_football_context = (
        _has_any(combined, FOOTBALL_MARKERS)
        or bool(entities.players)
        or bool(entities.teams)
    )
    pronoun_followup = _has_any(text, PRONOUN_OR_FOLLOWUP_MARKERS) and has_football_context

    score = 0
    reason_codes = []
    if _has_any(text, RELATIVE_TIME_MARKERS):
        score += 3
        reason_codes.append("relative_time")
    if _has_any(combined, CURRENT_FACT_MARKERS):
        score += 5
        reason_codes.append("current_fact_marker")
    if has_football_context:
        score += 2
        reason_codes.append("football_context")
    if reply_text and _has_any(reply_text, FOOTBALL_MARKERS + CURRENT_FACT_MARKERS):
        score += 3
        reason_codes.append("reply_context")
    if recent_messages and _has_any(context_text, FOOTBALL_MARKERS + CURRENT_FACT_MARKERS):
        score += 3
        reason_codes.append("recent_context")
    if _has_any(combined, NEWS_OR_X_MARKERS):
        score += 4
        reason_codes.append("news_or_x_source")
    if pronoun_followup:
        score += 3
        reason_codes.append("contextual_followup")

    if not has_football_context and not _has_any(text, ("转会", "罗马诺", "英超", "欧冠")):
        return FreshnessDecision()

    intent_name = _intent_for_current_text(text, context_text)
    mode = "required" if score >= 6 else "optional" if score >= 3 else "none"
    confidence = min(0.99, max(0.0, float(score) / 10.0))
    preferred = ["grok_search"]
    if intent_name in {"current_fixture", "current_standings", "recent_match_result", "current_team_evaluation"}:
        preferred = ["web_search"]
    if intent_name in {"transfer_status", "injury_status", "breaking_football_news"}:
        preferred = ["grok_search"]

    if mode == "none":
        return FreshnessDecision(
            mode="none",
            domain="football" if has_football_context else "",
            intent=intent_name,
            confidence=confidence,
            reason_codes=reason_codes,
            resolved_entities=entities.players + entities.teams,
        )

    return FreshnessDecision(
        mode=mode,
        domain="football",
        intent=intent_name,
        confidence=confidence,
        freshness_window="day" if mode == "required" else "",
        preferred_web_tools=preferred,
        reason_codes=reason_codes,
        resolved_entities=entities.players + entities.teams,
        query_hint=_query_hint(text, intent_name, entities),
    )
