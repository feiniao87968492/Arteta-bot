import hashlib
from dataclasses import dataclass
from typing import List, Optional

from .history import latest_reaction, recent_automatic_asset_names
from .models import EmojiAsset, EmojiReactionDecision


MIN_CANDIDATE_SCORE = 5.0
TOP_K = 3


SECONDARY_REACTION_MATCHES = {
    "celebration": ("approval", "surprised"),
    "approval": ("celebration", "encouraging"),
    "amused": ("teasing", "speechless"),
    "teasing": ("amused", "speechless"),
    "surprised": ("celebration", "speechless"),
    "speechless": ("frustrated", "surprised", "amused"),
    "thinking": ("skeptical",),
    "skeptical": ("thinking", "speechless"),
    "encouraging": ("comforting", "approval"),
    "comforting": ("encouraging", "sad"),
    "frustrated": ("speechless", "sad"),
    "sad": ("comforting", "frustrated"),
}

LEGACY_MOOD_REACTIONS = {
    "positive_neutral": "approval",
    "positive": "approval",
    "neutral": "approval",
    "negative": "frustrated",
    "消极": "frustrated",
    "负面": "frustrated",
}


@dataclass(frozen=True)
class RankedEmojiAsset(object):
    asset: EmojiAsset
    score: float


def _normalize_text(value: str) -> str:
    return str(value or "").strip().lower()


def _effective_decision(decision: EmojiReactionDecision, legacy_mood: str = "") -> EmojiReactionDecision:
    if decision.reaction != "none":
        return decision
    mapped = LEGACY_MOOD_REACTIONS.get(_normalize_text(legacy_mood))
    if not mapped:
        return decision
    return EmojiReactionDecision(
        reaction=mapped,
        intensity=decision.intensity,
        stance=decision.stance,
        topic=decision.topic,
        confidence=max(decision.confidence, 0.7),
        reason_codes=list(decision.reason_codes or []) + ["legacy_mood_compat"],
    )


def _explicit_name_matches(asset: EmojiAsset, explicit_emoji_name: str) -> bool:
    explicit = _normalize_text(explicit_emoji_name)
    if not explicit:
        return False
    return explicit in {
        _normalize_text(asset.name),
        _normalize_text(asset.relative_path),
    }


def score_emoji_asset(
    asset: EmojiAsset,
    decision: EmojiReactionDecision,
    group_id: str = "",
    explicit_emoji_name: str = "",
) -> Optional[float]:
    decision_contexts = set(decision.reason_codes or [])
    decision_contexts.add(decision.topic)
    if any(context in decision_contexts for context in asset.avoid_contexts):
        return None

    explicit_match = _explicit_name_matches(asset, explicit_emoji_name)
    recent_names = set(recent_automatic_asset_names(group_id, limit=5))
    if asset.name in recent_names and not explicit_match:
        return None

    score = 0.0
    reaction_score = 0.0
    if decision.reaction in asset.reactions:
        reaction_score = 6.0
    elif any(reaction in asset.reactions for reaction in SECONDARY_REACTION_MATCHES.get(decision.reaction, ())):
        reaction_score = 3.0
    score += reaction_score

    if explicit_match:
        score += 8.0
    elif reaction_score <= 0.0:
        return None

    if decision.stance in asset.stances:
        score += 2.0
    if decision.intensity in asset.intensities:
        score += 2.0
    if decision.topic in asset.topics:
        score += 1.0
    if latest_reaction(group_id) == decision.reaction:
        score -= 3.0
    if not asset.reviewed:
        score -= 2.0

    if score < MIN_CANDIDATE_SCORE:
        return None
    return score


def rank_emoji_candidates(
    assets: List[EmojiAsset],
    decision: EmojiReactionDecision,
    group_id: str = "",
    explicit_emoji_name: str = "",
    legacy_mood: str = "",
) -> List[RankedEmojiAsset]:
    effective = _effective_decision(decision, legacy_mood=legacy_mood)
    if effective.reaction == "none" and not explicit_emoji_name:
        return []

    ranked = []
    for asset in assets or []:
        score = score_emoji_asset(asset, effective, group_id=group_id, explicit_emoji_name=explicit_emoji_name)
        if score is None:
            continue
        ranked.append(RankedEmojiAsset(asset=asset, score=score))
    return sorted(ranked, key=lambda item: (-item.score, item.asset.name))


def _stable_weighted_index(ranked: List[RankedEmojiAsset], seed_text: str) -> int:
    weights = [max(0.01, item.score * max(item.asset.weight, 0.01)) for item in ranked]
    total = sum(weights)
    digest = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    marker = (int(digest[:16], 16) % 1000000) / 1000000.0 * total
    current = 0.0
    for index, weight in enumerate(weights):
        current += weight
        if marker <= current:
            return index
    return len(ranked) - 1


def select_emoji_asset(
    assets: List[EmojiAsset],
    decision: EmojiReactionDecision,
    group_id: str = "",
    request_id: str = "",
    explicit_emoji_name: str = "",
    legacy_mood: str = "",
) -> Optional[EmojiAsset]:
    effective = _effective_decision(decision, legacy_mood=legacy_mood)
    ranked = rank_emoji_candidates(
        assets,
        effective,
        group_id=group_id,
        explicit_emoji_name=explicit_emoji_name,
    )
    if not ranked:
        return None
    top = ranked[:TOP_K]
    seed_text = "{0}|{1}|{2}".format(group_id or "", request_id or "", effective.reaction)
    return top[_stable_weighted_index(top, seed_text)].asset
