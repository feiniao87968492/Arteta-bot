import argparse
import json
import os
import re
import sys
from collections import Counter
from typing import Dict, List, Optional


SAMPLE_HEADERS = [
    "#",
    "scenario",
    "user input summary",
    "screenshot path or reference",
    "progress sequence",
    "real tool order",
    "final answer structure and length",
    "transport",
    "reporter closed before final reply",
    "internal parameter leak",
    "pass/fail",
    "notes",
]

BEFORE_AFTER_HEADERS = [
    "item",
    "before screenshot",
    "after screenshot",
    "what changed",
    "pass/fail",
    "notes",
]

EXPECTED_SCENARIOS = [
    "One-word greeting",
    "Short football opinion",
    "Image or meme explanation",
    "Latest injury",
    "Transfer news",
    "Math short question",
    "Algorithm question",
    "Document summary",
    "Group memory",
    "Explicit concise request",
    "Tool timeout fallback",
    "Admin confirmation tool",
]

NO_TOOL_SCENARIOS = set([
    "one-word greeting",
    "short football opinion",
    "explicit concise request",
])

REQUIRED_SAMPLE_FIELDS = [
    "scenario",
    "user input summary",
    "screenshot path or reference",
    "progress sequence",
    "real tool order",
    "final answer structure and length",
    "transport",
    "reporter closed before final reply",
    "internal parameter leak",
    "pass/fail",
]

REQUIRED_BEFORE_AFTER_FIELDS = [
    "before screenshot",
    "after screenshot",
    "what changed",
    "pass/fail",
]

ALLOWED_PROGRESS_LABELS = set([
    "[agent]",
    "[plan]",
    "[action]",
    "[observation]",
    "[confirmation]",
])

FORBIDDEN_PROGRESS_PATTERNS = [
    ("[thought]", "progress sequence must not expose [Thought]"),
    ("group_id", "progress sequence must not expose group_id"),
    ("user_id", "progress sequence must not expose user_id"),
    ("prompt", "progress sequence must not expose prompt text"),
    ("traceback", "progress sequence must not expose raw exception bodies"),
    ("raw exception", "progress sequence must not expose raw exception bodies"),
    ("http://", "progress sequence must not expose URLs"),
    ("https://", "progress sequence must not expose URLs"),
]

NO_TOOL_VALUES = set(["n/a", "na", "none", "no", "-"])
PASS_VALUES = set(["pass", "passed", "yes", "ok", "\u901a\u8fc7"])
TRUE_VALUES = set(["yes", "y", "true", "pass", "passed", "ok", "\u662f", "\u901a\u8fc7"])
FALSE_VALUES = set(["no", "n", "false", "none", "n/a", "na", "\u5426"])
TRANSPORT_VALUE = "image"


def _split_table_line(line: str) -> List[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_separator_row(cells: List[str]) -> bool:
    return all(re.match(r"^:?-{3,}:?$", cell.strip()) for cell in cells if cell.strip())


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _table_rows(lines: List[str], expected_headers: List[str]) -> List[Dict[str, str]]:
    rows = []
    expected = [_normalize(header) for header in expected_headers]
    for index, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        cells = _split_table_line(line)
        if [_normalize(cell) for cell in cells] != expected:
            continue
        for row_line in lines[index + 1:]:
            if not row_line.strip().startswith("|"):
                break
            row_cells = _split_table_line(row_line)
            if _is_separator_row(row_cells):
                continue
            if len(row_cells) < len(expected_headers):
                row_cells.extend([""] * (len(expected_headers) - len(row_cells)))
            rows.append(dict(zip(expected_headers, row_cells[:len(expected_headers)])))
        break
    return rows


def _is_missing(value: str) -> bool:
    return str(value or "").strip() == ""


def _valid_pass(value: str) -> bool:
    return _normalize(value) in PASS_VALUES


def _markdown_link_target(value: str) -> str:
    raw = str(value or "").strip().strip("`")
    match = re.match(r"^\[[^\]]+\]\(([^)]+)\)$", raw)
    if match:
        return match.group(1).strip()
    return raw


def _resolve_evidence_path(value: str, repo_root: str, evidence_file: str) -> Optional[str]:
    raw = _markdown_link_target(value)
    if not raw:
        return None
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw):
        return None
    candidates = []
    if os.path.isabs(raw):
        candidates.append(raw)
    else:
        candidates.append(os.path.join(repo_root, raw))
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(evidence_file)), raw))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return None


def _contains_emoji(value: str) -> bool:
    for char in str(value or ""):
        codepoint = ord(char)
        if (
            0x1F300 <= codepoint <= 0x1FAFF
            or 0x2600 <= codepoint <= 0x27BF
        ):
            return True
    return False


def _validate_progress_sequence(value: str, prefix: str, errors: List[str]) -> None:
    normalized = _normalize(value)
    labels = re.findall(r"\[[^\]]+\]", str(value or ""))
    if not labels:
        errors.append("{0}: progress sequence must include at least one allowed progress label".format(prefix))
    for label in labels:
        if _normalize(label) not in ALLOWED_PROGRESS_LABELS:
            errors.append("{0}: progress sequence contains disallowed label {1}".format(prefix, label))
    for needle, message in FORBIDDEN_PROGRESS_PATTERNS:
        if needle in normalized:
            errors.append("{0}: {1}".format(prefix, message))
    if _contains_emoji(value):
        errors.append("{0}: progress sequence must not contain emoji".format(prefix))


def _validate_sample_row(row: Dict[str, str], repo_root: str, evidence_file: str, index: int, errors: List[str]) -> None:
    prefix = "sample row {0}".format(index)
    for field in REQUIRED_SAMPLE_FIELDS:
        if _is_missing(row.get(field, "")):
            errors.append("{0}: missing {1}".format(prefix, field))

    scenario = row.get("scenario", "")
    normalized_scenario = _normalize(scenario)
    if scenario not in EXPECTED_SCENARIOS:
        errors.append("{0}: unexpected scenario {1!r}".format(prefix, scenario))

    screenshot = row.get("screenshot path or reference", "")
    if not _resolve_evidence_path(screenshot, repo_root, evidence_file):
        errors.append("{0}: screenshot file does not exist: {1}".format(prefix, screenshot))

    _validate_progress_sequence(row.get("progress sequence", ""), prefix, errors)

    tool_order = _normalize(row.get("real tool order", ""))
    if normalized_scenario not in NO_TOOL_SCENARIOS and tool_order in NO_TOOL_VALUES:
        errors.append("{0}: real tool order is required for tool-backed scenario {1!r}".format(prefix, scenario))

    if _normalize(row.get("transport", "")) != TRANSPORT_VALUE:
        errors.append("{0}: transport must be image".format(prefix))
    if _normalize(row.get("reporter closed before final reply", "")) not in TRUE_VALUES:
        errors.append("{0}: reporter closed before final reply must be yes/pass".format(prefix))
    if _normalize(row.get("internal parameter leak", "")) not in FALSE_VALUES:
        errors.append("{0}: internal parameter leak must be no".format(prefix))
    if not _valid_pass(row.get("pass/fail", "")):
        errors.append("{0}: pass/fail must be Pass".format(prefix))


def _validate_before_after_row(row: Dict[str, str], repo_root: str, evidence_file: str, index: int, errors: List[str]) -> None:
    prefix = "before/after row {0}".format(index)
    for field in REQUIRED_BEFORE_AFTER_FIELDS:
        if _is_missing(row.get(field, "")):
            errors.append("{0}: missing {1}".format(prefix, field))
    if not _valid_pass(row.get("pass/fail", "")):
        errors.append("{0}: pass/fail must be Pass".format(prefix))
    for field in ["before screenshot", "after screenshot"]:
        value = row.get(field, "")
        if not _resolve_evidence_path(value, repo_root, evidence_file):
            errors.append("{0}: {1} file does not exist: {2}".format(prefix, field, value))


def validate_manual_evidence(evidence_path: str, repo_root: Optional[str] = None) -> Dict[str, object]:
    evidence_file = os.path.abspath(evidence_path)
    root = os.path.abspath(repo_root or os.getcwd())
    errors = []
    if not os.path.isfile(evidence_file):
        return {
            "ok": False,
            "sample_rows": 0,
            "before_after_rows": 0,
            "scenario_counts": {},
            "errors": ["evidence file does not exist: {0}".format(evidence_path)],
        }

    with open(evidence_file, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    sample_rows = _table_rows(lines, SAMPLE_HEADERS)
    before_after_rows = _table_rows(lines, BEFORE_AFTER_HEADERS)

    if len(sample_rows) != len(EXPECTED_SCENARIOS):
        errors.append("expected 12 sample rows, found {0}".format(len(sample_rows)))
    if len(before_after_rows) < 5:
        errors.append("expected at least 5 before/after rows, found {0}".format(len(before_after_rows)))

    normalized_counts = Counter(_normalize(row.get("scenario", "")) for row in sample_rows)
    scenario_counts = {}
    for scenario in EXPECTED_SCENARIOS:
        actual = normalized_counts.get(_normalize(scenario), 0)
        scenario_counts[scenario] = actual
        if actual != 1:
            errors.append("scenario {0!r}: expected 1, found {1}".format(scenario, actual))

    for index, row in enumerate(sample_rows, 1):
        _validate_sample_row(row, root, evidence_file, index, errors)
    for index, row in enumerate(before_after_rows, 1):
        _validate_before_after_row(row, root, evidence_file, index, errors)

    return {
        "ok": not errors,
        "sample_rows": len(sample_rows),
        "before_after_rows": len(before_after_rows),
        "scenario_counts": scenario_counts,
        "errors": errors,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Arteta agent progress long-form manual acceptance evidence.")
    parser.add_argument(
        "evidence",
        nargs="?",
        default="Docs/dev/agent-progress-longform-manual-evidence.md",
        help="Markdown evidence file to validate.",
    )
    parser.add_argument("--repo-root", default=".", help="Repository root used to resolve screenshot paths.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    result = validate_manual_evidence(args.evidence, repo_root=args.repo_root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        status = "passed" if result["ok"] else "failed"
        print("agent progress manual evidence validation {0}".format(status))
        print("sample rows: {0}".format(result["sample_rows"]))
        print("before/after rows: {0}".format(result["before_after_rows"]))
        for error in result["errors"]:
            print("- {0}".format(error))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
