import argparse
import json
import os
import sys
from typing import Any, Dict, Iterable, List

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from plugins.arteta_agent.context import ToolContext
from plugins.arteta_agent.routing.heuristic_router import route_message


LABELS = ("WEB_REQUIRED", "WEB_OPTIONAL", "WEB_NOT_NEEDED")


def _context_from_record(record: Dict[str, Any]) -> ToolContext:
    recent_context = record.get("recent_context") or []
    if isinstance(recent_context, str):
        recent_context = [recent_context]
    return ToolContext(
        bot=None,
        event=None,
        user_id="freshness-eval-user",
        group_id=str(record.get("group_id") or "freshness-eval-group"),
        nickname=str(record.get("nickname") or ""),
        raw_message=str(record.get("message") or ""),
        reply_text=str(record.get("replied_message") or record.get("reply_text") or ""),
        is_group=True,
        is_admin=False,
        extra={
            "recent_messages": list(recent_context or [])[:8],
            "detected_urls": list(record.get("source_urls") or record.get("detected_urls") or []),
        },
    )


def _label_for_mode(mode: str) -> str:
    if mode == "required":
        return "WEB_REQUIRED"
    if mode == "optional":
        return "WEB_OPTIONAL"
    return "WEB_NOT_NEEDED"


def _new_matrix() -> Dict[str, Dict[str, int]]:
    return dict(
        (expected, dict((predicted, 0) for predicted in LABELS))
        for expected in LABELS
    )


def evaluate_records(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    matrix = _new_matrix()
    rows = []
    mismatches = []
    total = 0
    for index, record in enumerate(records):
        total += 1
        expected = str(record.get("label") or "").strip()
        if expected not in LABELS:
            raise ValueError("record {0} has unsupported label: {1}".format(index, expected))
        message = str(record.get("message") or "")
        ctx = _context_from_record(record)
        decision = route_message([{"role": "user", "content": message}], ctx)
        predicted = _label_for_mode(getattr(decision.freshness, "mode", "none"))
        matrix[expected][predicted] += 1
        row = {
            "index": index,
            "expected": expected,
            "predicted": predicted,
            "intent": getattr(decision.freshness, "intent", ""),
            "reason_codes": list(getattr(decision.freshness, "reason_codes", []) or []),
            "resolved_entities": list(getattr(decision.freshness, "resolved_entities", []) or []),
        }
        expected_intent = str(record.get("expected_intent") or "").strip()
        if expected_intent:
            row["expected_intent"] = expected_intent
        expected_entity = str(record.get("expected_entity") or "").strip()
        if expected_entity:
            row["expected_entity"] = expected_entity
        rows.append(row)
        if predicted != expected:
            mismatches.append(row)

    required_true_positive = matrix["WEB_REQUIRED"]["WEB_REQUIRED"]
    required_false_negative = (
        matrix["WEB_REQUIRED"]["WEB_OPTIONAL"]
        + matrix["WEB_REQUIRED"]["WEB_NOT_NEEDED"]
    )
    required_false_positive = (
        matrix["WEB_OPTIONAL"]["WEB_REQUIRED"]
        + matrix["WEB_NOT_NEEDED"]["WEB_REQUIRED"]
    )
    required_recall_denominator = required_true_positive + required_false_negative
    required_precision_denominator = required_true_positive + required_false_positive
    required_recall = (
        float(required_true_positive) / float(required_recall_denominator)
        if required_recall_denominator
        else 0.0
    )
    required_precision = (
        float(required_true_positive) / float(required_precision_denominator)
        if required_precision_denominator
        else 0.0
    )
    return {
        "total": total,
        "labels": list(LABELS),
        "confusion_matrix": matrix,
        "required_recall": required_recall,
        "required_precision": required_precision,
        "mismatches": mismatches,
        "rows": rows,
    }


def load_records(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        data = data.get("records") or []
    if not isinstance(data, list):
        raise ValueError("dataset must be a list or an object with records")
    return [dict(item) for item in data]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Arteta Agent football freshness routing.")
    parser.add_argument(
        "--dataset",
        default=os.path.join("tests", "fixtures", "agent_freshness_eval.json"),
        help="JSON dataset containing labeled football freshness records.",
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
