"""Source ranking and claim verification helpers for Web access tools."""

import re
from dataclasses import dataclass
from html import unescape
from typing import Tuple
from urllib.parse import urlparse


MAX_EXCERPT_CHARS = 1800

PRIMARY_DOMAINS = (
    "arsenal.com",
    "premierleague.com",
    "uefa.com",
    "fifa.com",
    "thefa.com",
    "gov.uk",
    ".gov",
    ".edu",
    ".ac.uk",
)

AUTHORITATIVE_MEDIA_DOMAINS = (
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "theguardian.com",
    "theathletic.com",
    "skysports.com",
    "espn.com",
)


@dataclass
class _VerificationEvidence(object):
    url: str
    title: str
    source_level: str
    stance: str
    excerpt: str
    fetched: bool = True


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(str(text or ""))).strip()


def _search_result_url(item: dict) -> str:
    return str(item.get("href") or item.get("url") or item.get("link") or "").strip()


def _domain(url: str) -> str:
    parsed = urlparse(str(url or ""))
    domain = (parsed.hostname or parsed.netloc).lower()
    return domain[4:] if domain.startswith("www.") else domain


def _domain_matches(domain: str, item: str) -> bool:
    value = str(item or "").lower()
    if value.startswith("."):
        return domain.endswith(value)
    return domain == value or domain.endswith("." + value)


def _source_level(url: str) -> str:
    domain = _domain(url)
    if any(_domain_matches(domain, item) for item in PRIMARY_DOMAINS):
        return "一手/官方来源"
    if any(domain == item or domain.endswith("." + item) for item in AUTHORITATIVE_MEDIA_DOMAINS):
        return "权威媒体来源"
    return "普通网页来源"


def _claim_result_score(claim: str, item: dict) -> int:
    url = _search_result_url(item)
    title = str(item.get("title") or item.get("name") or "")
    snippet = str(item.get("body") or item.get("snippet") or item.get("description") or "")
    haystack = (title + " " + snippet + " " + url).lower()
    claim_text = str(claim or "").lower()

    source_level = _source_level(url)
    score = {"一手/官方来源": 6, "权威媒体来源": 4, "普通网页来源": 1}.get(source_level, 0)

    is_match_claim = any(token in claim_text for token in (
        "比赛", "比分", "赛果", "赛程",
        "match", "score", "result", "fixture",
    ))

    if is_match_claim:
        if re.search(r"\d+\s*[-:]\s*\d+", haystack):
            score += 8
        if "比赛" in haystack or "比分" in haystack or "赛果" in haystack:
            score += 2
        if "match" in haystack or "score" in haystack or "result" in haystack:
            score += 2
        if "集锦" in haystack or "加时" in haystack or "战胜" in haystack or "决赛" in haystack:
            score += 3

        domain = _domain(url)
        if any(value in domain for value in ("sports.cctv.com", "espn.com", "flashscore.com", "sofascore.com")):
            score += 3
        if "/teams/" in url or "/squad" in url:
            score -= 5

    return score


def _is_strong_match_result(claim: str, item: dict) -> bool:
    return _claim_result_score(claim, item) >= 12


def _claim_tokens(text: str) -> list:
    tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", str(text or "").lower())
    stopwords = set([
        "a", "an", "the", "to", "of", "and", "or", "in", "on", "for", "with",
        "after", "before", "was", "were", "is", "are", "be", "been", "being",
    ])
    return [token for token in tokens if token not in stopwords and len(token) > 1]


def _token_overlap_ratio(claim: str, text: str) -> float:
    claim_tokens = set(_claim_tokens(claim))
    if not claim_tokens:
        return 0.0
    text_tokens = set(_claim_tokens(text))
    if not text_tokens:
        return 0.0
    return float(len(claim_tokens.intersection(text_tokens))) / float(len(claim_tokens))


def _contains_negation_near_claim(claim: str, text: str) -> bool:
    value = str(text or "").lower()
    negations = (
        "did not",
        "has not",
        "have not",
        "not signed",
        "not agree",
        "not completed",
        "false",
        "denied",
        "refuted",
        "no agreement",
        "未",
        "没有",
        "否认",
        "不属实",
        "辟谣",
    )
    if not any(term in value for term in negations):
        return False
    return _token_overlap_ratio(claim, value) >= 0.5


def _classify_evidence_stance(claim: str, page_text: str) -> str:
    normalized_claim = _clean_text(claim).lower()
    normalized_text = _clean_text(page_text).lower()
    if not normalized_text:
        return "unclear"
    if _contains_negation_near_claim(claim, normalized_text):
        return "refute"
    if normalized_claim and normalized_claim in normalized_text:
        return "support"
    if _token_overlap_ratio(claim, normalized_text) >= 0.75:
        return "support"
    return "unclear"


def _stance_label(stance: str) -> str:
    return {
        "support": "支持",
        "refute": "反驳",
        "unclear": "不明确",
    }.get(str(stance or ""), "不明确")


def _verdict_marker(verdict: str) -> str:
    return {
        "support": "supported",
        "refute": "refuted",
        "unclear": "unclear",
    }.get(str(verdict or ""), "unclear")


def _is_authoritative_source_level(source_level: str) -> bool:
    return source_level in ("一手/官方来源", "权威媒体来源")


def _select_verification_verdict(evidence: list) -> Tuple[str, list]:
    authoritative_support = [
        item for item in evidence
        if item.stance == "support" and _is_authoritative_source_level(item.source_level)
    ]
    authoritative_refute = [
        item for item in evidence
        if item.stance == "refute" and _is_authoritative_source_level(item.source_level)
    ]
    fetched_items = [item for item in evidence if item.fetched]
    limitations = []
    if authoritative_support and authoritative_refute:
        limitations.append("来源冲突：权威来源之间存在支持和反驳。")
        return "unclear", limitations
    if authoritative_support:
        return "support", limitations
    if authoritative_refute:
        return "refute", limitations
    if not fetched_items and evidence:
        limitations.append("搜索摘要不能单独确认该说法。")
    elif any(item.stance in ("support", "refute") for item in evidence):
        limitations.append("ordinary source only: 找到的支持/反驳线索不是官方或权威来源。")
    else:
        limitations.append("未找到足够明确的正文证据。")
    return "unclear", limitations


def _format_verification_result(claim: str, verdict: str, evidence: list, limitations: list) -> str:
    lines = [
        "核验结论：{0}".format(_stance_label(verdict)),
        "待核实说法：{0}".format(_clean_text(claim)),
        "证据：",
    ]
    for index, item in enumerate(evidence, start=1):
        lines.append("{0}. {1}".format(index, item.title or "(无标题)"))
        lines.append("   立场：{0}".format(_stance_label(item.stance)))
        lines.append("   来源等级：{0}".format(item.source_level))
        lines.append("   链接：{0}".format(item.url))
        if item.excerpt:
            lines.append("   摘录：{0}".format(_clean_text(item.excerpt)[:MAX_EXCERPT_CHARS]))
    if limitations:
        lines.append("局限：")
        for limitation in limitations:
            lines.append("- {0}".format(limitation))
    return "\n".join(lines)
