from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class LongFormResponsePolicy(object):
    mode: str = "expanded"
    minimum_sections: int = 3
    target_min_chars: int = 350
    target_max_chars: int = 900
    include_direct_answer: bool = True
    include_reasoning_summary: bool = True
    include_context_or_example: bool = True
    include_caveats: bool = False
    reason_codes: List[str] = field(default_factory=list)


CONCISE_MARKERS = (
    "简短",
    "简单点",
    "一句话",
    "一两句",
    "只给答案",
    "只告诉我答案",
    "别展开",
    "不用解释",
)
DEEP_MARKERS = (
    "详细",
    "全面",
    "展开",
    "深入",
    "完整",
    "拆一下",
    "讲讲",
)
TECHNICAL_MARKERS = (
    "数学",
    "物理",
    "算法",
    "代码",
    "leetcode",
    "公式",
    "方程",
    "正整数解",
    "复杂度",
)


def resolve_long_form_policy(
    message: str = "",
    has_image: bool = False,
    route_hint: str = "",
    current_information_required: bool = False,
    has_document: bool = False,
    has_url: bool = False,
    stop_reason: str = "",
    tool_failure: bool = False,
) -> LongFormResponsePolicy:
    text = str(message or "").strip().lower()
    route = str(route_hint or "")
    if stop_reason == "waiting_confirmation":
        return _policy("concise", 50, 180, ["permission_or_confirmation"], sections=1)
    if tool_failure:
        return _policy("concise", 80, 250, ["tool_failure"], sections=1, caveats=True)
    if any(marker in text for marker in CONCISE_MARKERS):
        return _policy("concise", 50, 250, ["explicit_concise_request"], sections=1)

    reasons = []
    if has_image:
        reasons.append("image")
    if has_document:
        reasons.append("document")
    if has_url or current_information_required or route in {"current_news", "web_required", "x_post"}:
        reasons.append("current_information")
    if any(marker in text for marker in TECHNICAL_MARKERS):
        reasons.append("technical_or_math")
    if any(marker in text for marker in DEEP_MARKERS):
        reasons.append("explicit_deep_request")
    if route in {"tactical_deep_dive"}:
        reasons.append("tactical_deep_dive")

    if any(reason in reasons for reason in (
        "technical_or_math",
        "explicit_deep_request",
        "document",
        "tactical_deep_dive",
    )):
        return _policy("deep", 500, 1600, reasons, sections=4, caveats=True)

    if "current_information" in reasons:
        return _policy("expanded", 500, 1000, reasons, sections=4, caveats=True)
    if has_image:
        return _policy("expanded", 300, 600, reasons or ["image"], sections=3)
    return _policy("expanded", 250, 900, ["short_input_long_answer"], sections=3)


def build_dynamic_response_constraints(policy: LongFormResponsePolicy) -> str:
    mode = str(policy.mode or "expanded")
    if mode == "concise":
        return "\n".join([
            "【本轮回答模式：concise】",
            "- 用户或执行状态要求简短，直接给结论或确认状态。",
            "- 不展开成长篇，不补无关背景。",
            "- 保持清楚准确，不输出工具参数、内部 Trace 或隐藏思维链。",
        ])
    if mode == "deep":
        return "\n".join([
            "【本轮回答模式：deep】",
            "- 给出完整方法、关键推导、结果校验和最终答案。",
            "- 第一部分直接回答，随后分层解释原因、过程、背景和影响。",
            "- 建议 4～8 个自然段；需要时使用列表、公式或代码块。",
            "- 保持阿尔特塔人格，但不要堆砌动作描写和战术口头禅。",
        ])
    return "\n".join([
        "【本轮回答模式：expanded】",
        "- 用户输入较短，也仍需充分展开；输入长度不决定回答长度。",
        "- 第一部分直接回答，随后解释原因，并补充背景、例子、影响或校验。",
        "- 建议 3～6 个自然段；不重复同义内容。",
        "- 保持阿尔特塔人格，但不要堆砌动作描写和战术口头禅。",
    ])


def _policy(mode: str, min_chars: int, max_chars: int, reasons, sections: int, caveats: bool = False) -> LongFormResponsePolicy:
    return LongFormResponsePolicy(
        mode=mode,
        minimum_sections=sections,
        target_min_chars=min_chars,
        target_max_chars=max_chars,
        include_caveats=caveats,
        reason_codes=list(reasons or []),
    )
