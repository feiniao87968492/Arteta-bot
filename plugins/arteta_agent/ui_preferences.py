import json
import os
import re
from pathlib import Path

from . import behavior_policy


ALLOWED_TARGETS = {
    # Whole rendered reply body; used for requests like "把回复文字放大五倍".
    "reply_body",
    "agent_trace_title",
    "agent_trace_tool_label",
    "agent_trace_detail",
}

NAMED_COLORS = {
    "black": "#111827",
    "white": "#ffffff",
    "red": "#db0007",
    "blue": "#0284c7",
    "green": "#16a34a",
    "gold": "#d7bf6a",
    "yellow": "#ca8a04",
    "orange": "#ea580c",
    "purple": "#9333ea",
    "pink": "#db2777",
}

COLOR_MARKERS = {
    "blue": ("[blue]", "[/blue]"),
    "red": ("[red]", "[/red]"),
    "none": ("", ""),
}

FONT_SIZE_MARKERS = {
    "normal": ("", ""),
    "large": ("[large]", "[/large]"),
}

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


def normalize_color(color: str) -> str:
    value = str(color or "").strip().lower()
    if not value:
        return ""
    if value == "none":
        return "none"
    if value in NAMED_COLORS:
        return value
    if len(value) in (3, 6) and all(ch in "0123456789abcdef" for ch in value):
        return "#{0}".format(value)
    if value.startswith("#"):
        raw = value[1:]
        if len(raw) in (3, 6) and all(ch in "0123456789abcdef" for ch in raw):
            return value
    raise ValueError("unsupported ui color: {0}".format(color))


def normalize_font_scale(font_scale) -> float:
    value = str(font_scale or "").strip().lower()
    if not value:
        return 0.0
    if value.endswith("x"):
        value = value[:-1]
    elif value.endswith("%"):
        value = str(float(value[:-1]) / 100.0)
    scale = float(value)
    if scale <= 0:
        raise ValueError("unsupported ui font_scale: {0}".format(font_scale))
    return scale


def normalize_font_size(font_size: str):
    value = str(font_size or "").strip().lower()
    if not value:
        return "", 0.0
    if value in FONT_SIZE_MARKERS:
        return value, 0.0
    return "", normalize_font_scale(value)


def extract_font_scale_from_text(text: str) -> float:
    value = str(text or "")
    compact = value.replace(" ", "").lower()
    match = re.search(r"(\d+(?:\.\d+)?)(?:倍|x)", compact)
    if match:
        return float(match.group(1))
    match = re.search(r"(\d+(?:\.\d+)?)%", compact)
    if match:
        return float(match.group(1)) / 100.0
    for word, number in CHINESE_NUMBERS.items():
        if "{0}倍".format(word) in value:
            return float(number)
    return 0.0


def _preferences_path() -> Path:
    configured = os.environ.get("ARTETA_AGENT_UI_PREFS_PATH")
    if configured:
        return Path(configured)
    return Path(os.getcwd()) / "config" / "agent_ui_preferences.json"


def _load_preferences() -> dict:
    path = _preferences_path()
    if not path.exists():
        return {"groups": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"groups": {}}
    if not isinstance(data, dict):
        return {"groups": {}}
    data.setdefault("groups", {})
    return data


def _save_preferences(data: dict) -> None:
    path = _preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def set_group_preference(group_id: str, target: str, color: str = "", bold=None, font_size: str = "", font_scale=None) -> dict:
    target = str(target or "").strip()
    color = normalize_color(color)
    font_size, parsed_scale = normalize_font_size(font_size)
    explicit_scale = normalize_font_scale(font_scale)
    scale = explicit_scale or parsed_scale
    if target not in ALLOWED_TARGETS:
        raise ValueError("unsupported ui target: {0}".format(target))
    current = behavior_policy.get_render_preference(group_id, target)
    if color:
        current["color"] = color
    if bold is not None:
        current["bold"] = bool(bold)
    if font_size:
        current["font_size"] = font_size
        current.pop("font_scale", None)
    if scale:
        current["font_scale"] = scale
        current.pop("font_size", None)
    behavior_policy.set_render_preference(group_id, target, current)
    return current


def set_phrase_preference(group_id: str, phrase: str, color: str = "", bold=None, font_size: str = "", font_scale=None) -> dict:
    phrase = str(phrase or "").strip()
    if not phrase:
        raise ValueError("empty ui phrase")
    color = normalize_color(color)
    font_size, parsed_scale = normalize_font_size(font_size)
    explicit_scale = normalize_font_scale(font_scale)
    scale = explicit_scale or parsed_scale
    rule = dict(behavior_policy.set_phrase_style(group_id, phrase, {}))
    if color:
        rule["color"] = color
    if bold is not None:
        rule["bold"] = bool(bold)
    if font_size:
        rule["font_size"] = font_size
        rule.pop("font_scale", None)
    if scale:
        rule["font_scale"] = scale
        rule.pop("font_size", None)
    behavior_policy.set_phrase_style(group_id, phrase, rule)
    return rule


def detect_phrase_style_preference(text: str) -> dict:
    value = str(text or "").strip()
    if not value or "回复" not in value:
        return {}
    phrase_match = re.search(r"[，,、]\s*([^，,。；;]+?)\s*(?:这个名字|这个词|这个短语|这句话)", value)
    if not phrase_match:
        phrase_match = re.search(r"[\"“']([^\"”']+)[\"”']\s*(?:这个名字|这个词|这个短语|这句话)?", value)
    if not phrase_match:
        return {}
    phrase = phrase_match.group(1).strip()
    if not phrase:
        return {}
    color = ""
    hex_match = re.search(r"(?:#|颜色是|色值是|换成|改成)?\s*([0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])", value)
    if hex_match:
        color = "#{0}".format(hex_match.group(1).lower())
    if "标红" in value or "红色" in value or "紅色" in value:
        color = "red"
    elif "标蓝" in value or "蓝色" in value or "藍色" in value:
        color = "blue"
    elif "深绿" in value or "深綠" in value or "dark green" in value.lower():
        color = "#006400"
    elif "浅绿" in value or "淺綠" in value or "light green" in value.lower():
        color = "#86efac"
    elif "亮绿" in value or "亮綠" in value:
        color = "#22c55e"
    elif "绿色" in value or "綠色" in value:
        color = "green"
    elif "金色" in value:
        color = "gold"
    bold = True if ("加粗" in value or "粗体" in value or "粗體" in value) else None
    scale = extract_font_scale_from_text(value)
    if not color and bold is None and not scale:
        return {}
    out = {"phrase": phrase}
    if color:
        out["color"] = color
    if bold is not None:
        out["bold"] = bold
    if scale:
        out["font_scale"] = scale
    return out


def get_group_preference(group_id: str, target: str) -> dict:
    return behavior_policy.get_render_preference(group_id, target)


def get_phrase_preferences(group_id: str) -> list:
    return behavior_policy.get_phrase_styles(group_id)


def _policy_value(group_id: str, key: str):
    return behavior_policy.get_group_policy(group_id, key).get("value")


def _split_target_names(value) -> list:
    if isinstance(value, list):
        items = value
    else:
        items = re.split(r"[、,，;；\n]+", str(value or ""))
    names = []
    for item in items:
        name = str(item or "").strip().strip("`'\"“”")
        if name:
            names.append(name)
    return names


def _name_highlight_rules(group_id: str) -> list:
    raw_pref = _policy_value(group_id, "render.reply_body.name_highlight")
    if isinstance(raw_pref, dict):
        pref = dict(raw_pref)
        names = _split_target_names(pref.get("target_names"))
    else:
        pref = {"color": raw_pref}
        names = _split_target_names(_policy_value(group_id, "render.reply_body.target_names"))
    color = normalize_color(pref.get("color") or "")
    if not color or color == "none":
        return []
    base_rule = dict(pref)
    base_rule["color"] = color
    base_rule.pop("target_names", None)
    return [dict(base_rule, phrase=name) for name in names]


def _wrap_with_preference(text: str, pref: dict) -> str:
    color = str(pref.get("color") or "").lower()
    font_scale = pref.get("font_scale")
    font_size = str(pref.get("font_size") or "").lower()
    wrappers = []
    if color in COLOR_MARKERS:
        color_start, color_end = COLOR_MARKERS.get(color, ("", ""))
    elif color and color != "none":
        color_start, color_end = ("[color={0}]".format(color), "[/color]")
    else:
        color_start, color_end = ("", "")
    if color_start:
        wrappers.append((color_start, color_end))
    if pref.get("bold") is True:
        wrappers.append(("[bold]", "[/bold]"))
    if font_scale:
        wrappers.append(("[scale={0:g}]".format(float(font_scale)), "[/scale]"))
    else:
        size_start, size_end = FONT_SIZE_MARKERS.get(font_size, ("", ""))
        if size_start:
            wrappers.append((size_start, size_end))
    styled = text
    for start, end in reversed(wrappers):
        styled = "{0}{1}{2}".format(start, styled, end)
    return styled


def apply_text_preferences(text: str, group_id: str) -> str:
    result = str(text or "")
    rules = get_phrase_preferences(group_id) + _name_highlight_rules(group_id)
    rules = sorted(rules, key=lambda item: len(str(item.get("phrase") or "")), reverse=True)
    for rule in rules:
        phrase = str(rule.get("phrase") or "").strip()
        if not phrase or phrase not in result:
            continue
        styled = _wrap_with_preference(phrase, rule)
        result = result.replace(phrase, styled)
    # Apply group-level reply styling after phrase rules so explicit phrase
    # styles still stay inside the final whole-reply wrapper.
    result = apply_group_style(result, group_id, "reply_body")
    return result


def apply_group_style(text: str, group_id: str, target: str) -> str:
    pref = get_group_preference(group_id, target)
    color = str(pref.get("color") or "").lower()
    font_size = str(pref.get("font_size") or "").lower()
    font_scale = pref.get("font_scale")
    return _wrap_with_preference(text, {
        "color": color,
        "bold": pref.get("bold"),
        "font_size": font_size,
        "font_scale": font_scale,
    })
