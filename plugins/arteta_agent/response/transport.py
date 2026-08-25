import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ReplyTransportDecision(object):
    mode: str
    reason: str


_TABLE_SEPARATOR_RE = re.compile(r"(?m)^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_MATH_RE = re.compile(r"\$\$?[^$]+\$\$?")
_STYLE_TAG_RE = re.compile(r"\[/?(?:red|blue|green|bold|large|color=[^\]]+|scale(?:=[^\]]+)?)\]")


def choose_reply_transport(
    text: str,
    has_image_artifact: bool = False,
    user_requested_image: bool = False,
    plain_text_limit: int = 350,
) -> ReplyTransportDecision:
    body = str(text or "").strip()
    if has_image_artifact:
        return ReplyTransportDecision("image", "image_artifact")
    if user_requested_image:
        return ReplyTransportDecision("image", "user_requested_image")
    if "```" in body:
        return ReplyTransportDecision("image", "code_block")
    if _MATH_RE.search(body):
        return ReplyTransportDecision("image", "math")
    if _TABLE_SEPARATOR_RE.search(body):
        return ReplyTransportDecision("image", "table")
    if _STYLE_TAG_RE.search(body):
        return ReplyTransportDecision("image", "rich_style")
    if len(body) > plain_text_limit and _looks_structured(body):
        return ReplyTransportDecision("image", "long_structured_content")
    if len(body) > plain_text_limit * 2:
        return ReplyTransportDecision("image", "long_text")
    return ReplyTransportDecision("text", "short_plain_text")


def _looks_structured(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if len(lines) >= 8:
        return True
    if sum(1 for line in lines if line.startswith(("- ", "* ", "1. ", "2. ", "3. "))) >= 3:
        return True
    if any(line.startswith("#") or (line.startswith("**") and line.endswith("**")) for line in lines):
        return True
    return False
