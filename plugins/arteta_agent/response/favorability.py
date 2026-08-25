import re
from dataclasses import dataclass
from typing import Optional, Tuple


LEGACY_FAVOR_MARKERS = (
    "【好感度+++】",
    "【好感度++】",
    "【好感度+】",
    "【好感度=】",
    "【好感度-】",
    "【好感度--】",
    "【好感度---】",
)


@dataclass(frozen=True)
class FavorabilityDecision(object):
    delta: int = 0
    reason: str = ""


def strip_legacy_favor_markers(text: str) -> Tuple[str, Optional[str]]:
    found = []
    for marker in LEGACY_FAVOR_MARKERS:
        for match in re.finditer(re.escape(marker), str(text or "")):
            found.append((match.start(), marker))
    if not found:
        return str(text or ""), None
    found.sort(key=lambda item: item[0])
    marker = found[-1][1]
    clean = re.sub(r"\s*" + re.escape(marker) + r"\s*$", "", str(text or "")).rstrip()
    return clean, marker


def _contains_any(text: str, markers) -> bool:
    return any(marker in text for marker in markers)


def evaluate_favorability(user_message: str, assistant_reply: str = "", is_admin: bool = False) -> FavorabilityDecision:
    if is_admin:
        return FavorabilityDecision(0, "")
    text = "{0}\n{1}".format(user_message or "", assistant_reply or "").lower()

    heavy_negative = (
        "傻逼",
        "废物教练",
        "垃圾教练",
        "阿尔特塔滚",
        "arteta滚",
        "滚出阿森纳",
        "下课吧",
    )
    moderate_negative = (
        "废物",
        "垃圾",
        "sb",
        "滚",
        "下课",
        "恶心",
        "真菜",
    )
    light_negative = (
        "不行",
        "失望",
        "摆烂",
        "拉胯",
        "抽象",
    )
    if _contains_any(text, heavy_negative):
        return FavorabilityDecision(-8, "严重负面言行")
    if _contains_any(text, moderate_negative):
        return FavorabilityDecision(-3, "负面言行")
    if _contains_any(text, light_negative):
        return FavorabilityDecision(-1, "轻微负面情绪")

    quality_markers = (
        "整理了",
        "来源",
        "赛程",
        "分析",
        "帮大家",
        "总结了",
    )
    if _contains_any(text, quality_markers) and _contains_any(text, ("来源", "赛程", "分析", "总结")):
        return FavorabilityDecision(2, "有价值的群体贡献")

    special_positive = (
        "长期整理",
        "持续整理",
        "完整复盘",
    )
    if _contains_any(text, special_positive):
        return FavorabilityDecision(3, "持续高质量贡献")

    return FavorabilityDecision(0, "")


def should_show_favorability_notice(
    delta: int,
    old_level: str,
    new_level: str,
    debug: bool = False,
    threshold: int = 4,
) -> bool:
    if debug:
        return True
    if str(old_level or "") != str(new_level or ""):
        return True
    return abs(int(delta or 0)) >= int(threshold)


def format_favorability_notice(
    delta: int,
    old_level: str,
    new_level: str,
    favor: int,
    debug: bool = False,
    threshold: int = 4,
) -> str:
    delta_value = int(delta or 0)
    if not should_show_favorability_notice(delta_value, old_level, new_level, debug=debug, threshold=threshold):
        return ""
    parts = []
    if delta_value > 0:
        parts.append("信任度上升{0}点".format(abs(delta_value)))
    elif delta_value < 0:
        parts.append("信任度下降{0}点".format(abs(delta_value)))
    elif debug:
        parts.append("信任度无变化")
    if str(old_level or "") != str(new_level or ""):
        parts.append("定位更新：{0}".format(new_level))
    if debug:
        parts.append("当前信任度：{0}".format(int(favor or 0)))
    return "【{0}】".format("；".join(parts)) if parts else ""
