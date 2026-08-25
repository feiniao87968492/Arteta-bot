import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, List


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


MODES = (
    "casual",
    "meme",
    "football_opinion",
    "current_news",
    "tactical_deep_dive",
    "serious",
)
PERSONA_INTENSITIES = ("light", "medium", "strong")
TARGET_LENGTHS = ("short", "medium", "long")


def load_records(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        data = data.get("records") or []
    if not isinstance(data, list):
        raise ValueError("dataset must be a list or an object with records")
    return [dict(item) for item in data]


def _bool_value(record: Dict[str, Any], key: str) -> bool:
    return bool(record.get(key))


def _tags(record: Dict[str, Any]) -> List[str]:
    raw = record.get("tags") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(item) for item in raw]


def _increment(counter: Dict[str, int], key: str) -> None:
    counter[key] = int(counter.get(key, 0)) + 1


def validate_records(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(records)
    mode_counts = dict((mode, 0) for mode in MODES)
    intensity_counts = dict((item, 0) for item in PERSONA_INTENSITIES)
    length_counts = dict((item, 0) for item in TARGET_LENGTHS)
    errors = []
    explicit_emoji_cases = 0
    trace_query_cases = 0
    image_cases = 0
    screenshot_regression_cases = 0

    for index, record in enumerate(rows):
        case_id = str(record.get("id") or index)
        message = str(record.get("message") or "").strip()
        if not message:
            errors.append("{0}: missing message".format(case_id))

        mode = str(record.get("expected_mode") or "").strip()
        if mode not in mode_counts:
            errors.append("{0}: unsupported expected_mode {1}".format(case_id, mode))
        else:
            _increment(mode_counts, mode)

        intensity = str(record.get("persona_intensity") or "").strip()
        if intensity not in intensity_counts:
            errors.append("{0}: unsupported persona_intensity {1}".format(case_id, intensity))
        else:
            _increment(intensity_counts, intensity)

        target_length = str(record.get("target_length") or "").strip()
        if target_length not in length_counts:
            errors.append("{0}: unsupported target_length {1}".format(case_id, target_length))
        else:
            _increment(length_counts, target_length)

        for key in (
            "allow_mood_emoji",
            "prefer_image_render",
            "show_trace",
            "show_favorability",
        ):
            if key not in record or not isinstance(record.get(key), bool):
                errors.append("{0}: {1} must be a boolean".format(case_id, key))

        tags = set(_tags(record))
        if "explicit_emoji" in tags or _bool_value(record, "allow_mood_emoji"):
            explicit_emoji_cases += 1
        if "trace_query" in tags or _bool_value(record, "show_trace"):
            trace_query_cases += 1
        if _bool_value(record, "has_image"):
            image_cases += 1
        if "screenshot_regression" in tags:
            screenshot_regression_cases += 1

    if errors:
        raise ValueError("; ".join(errors))

    return {
        "total": len(rows),
        "mode_counts": mode_counts,
        "persona_intensity_counts": intensity_counts,
        "target_length_counts": length_counts,
        "explicit_emoji_cases": explicit_emoji_cases,
        "trace_query_cases": trace_query_cases,
        "image_cases": image_cases,
        "screenshot_regression_cases": screenshot_regression_cases,
    }


def _read_repo_text(relative_path: str) -> str:
    path = os.path.join(REPO_ROOT, relative_path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def _count_prompt_hits(text: str, markers: Iterable[str]) -> int:
    return sum(1 for marker in markers if marker and marker in text)


def _current_code_baseline() -> Dict[str, Any]:
    try:
        from plugins.arteta_agent.prompts import ARTETA_DEFAULT_PROMPT

        prompt_text = ARTETA_DEFAULT_PROMPT
    except Exception:
        prompt_text = _read_repo_text(os.path.join("plugins", "arteta_agent", "prompts.py"))

    mood_forces_positive_neutral = False
    try:
        from plugins.arteta_agent.response.mood import detect_forced_mood_emoji_args

        args = detect_forced_mood_emoji_args(
            [{"role": "user", "content": "早"}],
            "早，今天训练保持专注。",
        )
        mood_forces_positive_neutral = args.get("mood") == "positive_neutral"
    except Exception:
        mood_forces_positive_neutral = False

    trace_prefixes_grok_marker = False
    try:
        from plugins.arteta_agent.response.composer import compose_final_response

        result = compose_final_response(
            "answer",
            trace={"tools": [{"markers": ["[grok]"]}]},
        )
        trace_prefixes_grok_marker = result.startswith("[grok]")
    except Exception:
        trace_prefixes_grok_marker = False

    fixed_action_markers = (
        "可以先" + "拍桌子",
        "拍" + "桌子",
        "敲" + "战术板",
        "推开" + "更衣室门",
        "第一句" + "就要有劲",
    )
    return {
        "fixed_opening_prompt_hits": _count_prompt_hits(prompt_text, fixed_action_markers),
        "mood_forces_positive_neutral": mood_forces_positive_neutral,
        "favorability_prompt_marker_required": (
            "好感度" in prompt_text
            and "必须" in prompt_text
            and "另起一行" in prompt_text
        ),
        "trace_prefixes_grok_marker": trace_prefixes_grok_marker,
    }


def _ratio(count: int, total: int) -> float:
    if not total:
        return 0.0
    return float(count) / float(total)


def _expected_ratios(records: List[Dict[str, Any]]) -> Dict[str, float]:
    total = len(records)
    return {
        "allow_mood_emoji": _ratio(sum(1 for item in records if _bool_value(item, "allow_mood_emoji")), total),
        "prefer_image_render": _ratio(sum(1 for item in records if _bool_value(item, "prefer_image_render")), total),
        "show_trace": _ratio(sum(1 for item in records if _bool_value(item, "show_trace")), total),
        "show_favorability": _ratio(sum(1 for item in records if _bool_value(item, "show_favorability")), total),
    }


def _risk_flags(records: List[Dict[str, Any]], baseline: Dict[str, Any]) -> Dict[str, int]:
    forced_neutral_emoji_cases = 0
    if baseline.get("mood_forces_positive_neutral"):
        forced_neutral_emoji_cases = sum(1 for item in records if not _bool_value(item, "allow_mood_emoji"))

    visible_favorability_cases = 0
    if baseline.get("favorability_prompt_marker_required"):
        visible_favorability_cases = sum(1 for item in records if not _bool_value(item, "show_favorability"))

    visible_trace_marker_cases = 0
    if baseline.get("trace_prefixes_grok_marker"):
        visible_trace_marker_cases = sum(1 for item in records if not _bool_value(item, "show_trace"))

    return {
        "forced_neutral_emoji_cases": forced_neutral_emoji_cases,
        "visible_favorability_cases": visible_favorability_cases,
        "visible_trace_marker_cases": visible_trace_marker_cases,
        "fixed_opening_prompt_hits": int(baseline.get("fixed_opening_prompt_hits") or 0),
    }


def evaluate_records(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(records)
    summary = validate_records(rows)
    baseline = _current_code_baseline()
    return {
        "total": summary["total"],
        "mode_counts": summary["mode_counts"],
        "persona_intensity_counts": summary["persona_intensity_counts"],
        "target_length_counts": summary["target_length_counts"],
        "expected_ratios": _expected_ratios(rows),
        "current_code_baseline": baseline,
        "risk_flags": _risk_flags(rows, baseline),
        "coverage": {
            "explicit_emoji_cases": summary["explicit_emoji_cases"],
            "trace_query_cases": summary["trace_query_cases"],
            "image_cases": summary["image_cases"],
            "screenshot_regression_cases": summary["screenshot_regression_cases"],
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Arteta response personality/style baseline.")
    parser.add_argument(
        "--dataset",
        default=os.path.join("tests", "fixtures", "personality_eval_cases.json"),
        help="JSON dataset containing anonymized personality response records.",
    )
    parser.add_argument("--output", default="", help="Optional path to write the JSON report.")
    args = parser.parse_args(argv)

    report = evaluate_records(load_records(args.dataset))
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output_dir = os.path.dirname(os.path.abspath(args.output))
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.write("\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
