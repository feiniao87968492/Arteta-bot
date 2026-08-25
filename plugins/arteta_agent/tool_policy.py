import re
from typing import Dict, Set

from . import behavior_policy


TOOL_NAME_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)")
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


def _parse_turns(text: str, default: int = 10) -> int:
    match = re.search(r"(\d+)\s*轮", text)
    if match:
        return max(1, min(int(match.group(1)), 100))
    for word, value in CHINESE_NUMBERS.items():
        if "{0}轮".format(word) in text:
            return value
    return default


def parse_tool_block_instruction(text: str) -> Dict[str, object]:
    # Turn natural-language test commands into an enforceable policy. This is
    # intentionally outside prompts so the model cannot "agree" and bypass it.
    value = str(text or "").strip()
    if not value:
        return {}
    if not any(marker in value for marker in ("禁止调用", "禁用", "不要调用", "别调用")):
        return {}
    if "tool" not in value.lower() and "工具" not in value:
        return {}
    names = [name for name in TOOL_NAME_RE.findall(value) if "_" in name]
    if not names:
        return {}
    return {
        "tool_name": names[-1],
        "turns": _parse_turns(value),
        "reason": value,
    }


def set_group_tool_block(group_id: str, tool_name: str, turns: int = 10, reason: str = "") -> dict:
    item = behavior_policy.set_tool_disabled(group_id, tool_name, turns=turns, reason=reason)
    return {
        "remaining_turns": int(item.get("ttl_turns") or 0),
        "reason": str(item.get("reason") or ""),
    }


def get_group_tool_blocks(group_id: str) -> Dict[str, dict]:
    blocks = {}
    for name in behavior_policy.get_disabled_tools(group_id):
        item = behavior_policy.get_group_policy(group_id, "tool.{0}.disabled".format(name))
        blocks[name] = {
            "remaining_turns": int(item.get("ttl_turns") or 0),
            "reason": str(item.get("reason") or ""),
        }
    return blocks


def get_disabled_tools(group_id: str) -> Set[str]:
    return behavior_policy.get_disabled_tools(group_id)


def consume_group_policy_turn(group_id: str) -> None:
    # Count down once per handled agent request. Expired tool blocks are removed
    # automatically so temporary test constraints do not become permanent.
    behavior_policy.consume_group_policy_turn(group_id)
