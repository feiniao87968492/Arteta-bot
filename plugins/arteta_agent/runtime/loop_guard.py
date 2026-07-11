import json
from hashlib import sha256
from typing import Dict

from .config import AgentRunConfig


def tool_call_signature(tool_call: dict) -> str:
    function = tool_call.get("function") or {}
    name = str(function.get("name") or "")
    raw_args = function.get("arguments") or "{}"
    try:
        args = json.loads(str(raw_args or "{}"))
    except json.JSONDecodeError:
        args = str(raw_args)
    canonical = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256("{0}:{1}".format(name, canonical).encode("utf-8")).hexdigest()


def loop_guard_message(reason: str) -> str:
    return (
        "[LoopGuard] Agent runtime stopped: {0}. Please answer from the "
        "evidence already gathered instead of calling more tools."
    ).format(reason)


class LoopGuard:
    def __init__(self, config: AgentRunConfig) -> None:
        self.config = config
        self.call_signatures: Dict[str, int] = {}

    def before_tool_call(self, tool_call: dict, executed_tool_count: int) -> str:
        if self.config.max_tool_calls > 0 and executed_tool_count >= self.config.max_tool_calls:
            return "tool call budget exhausted"
        signature = tool_call_signature(tool_call)
        seen_count = int(self.call_signatures.get(signature) or 0)
        if (
            self.config.max_same_tool_call_repeats > 0
            and seen_count >= self.config.max_same_tool_call_repeats
        ):
            return "repeated identical tool call"
        self.call_signatures[signature] = seen_count + 1
        return ""

    def after_observation(self, total_observation_chars: int) -> str:
        if (
            self.config.max_total_observation_chars > 0
            and total_observation_chars > self.config.max_total_observation_chars
        ):
            return "observation budget exceeded"
        return ""

