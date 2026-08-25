import argparse
import json
import os
import re
import sys
from collections import Counter
from typing import Dict, List, Optional


SAMPLE_HEADERS = [
    "#",
    "category",
    "user input summary",
    "screenshot path or reference",
    "first sentence",
    "character count",
    "paragraph count",
    "emoji sent",
    "transport",
    "trace visible",
    "favorability visible",
    "source display",
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

EXPECTED_SAMPLE_COUNTS = {
    "daily chat": 3,
    "meme/image": 2,
    "football opinion": 2,
    "latest news": 2,
    "tactical deep dive": 2,
    "trace query": 1,
}

REQUIRED_SAMPLE_FIELDS = [
    "user input summary",
    "screenshot path or reference",
    "first sentence",
    "character count",
    "paragraph count",
    "emoji sent",
    "transport",
    "trace visible",
    "favorability visible",
    "source display",
    "pass/fail",
]

REQUIRED_BEFORE_AFTER_FIELDS = [
    "before screenshot",
    "after screenshot",
    "what changed",
    "pass/fail",
]

PASS_VALUES = set(["pass", "passed", "yes", "ok", "通过"])
BOOLEAN_VALUES = set(["yes", "no", "是", "否", "n/a", "na", "none"])
TRANSPORT_VALUES = set(["text", "image"])


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


def _valid_positive_int(value: str) -> bool:
    try:
        return int(str(value).strip()) > 0
    except (TypeError, ValueError):
        return False


def _valid_pass(value: str) -> bool:
    return _normalize(value) in PASS_VALUES


def _resolve_evidence_path(value: str, repo_root: str, evidence_file: str) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw):
        # URL-like references are not local files. They can be useful notes,
        # but this validator is intended to prove screenshot evidence exists.
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


def _validate_sample_row(row: Dict[str, str], repo_root: str, evidence_file: str, index: int, errors: List[str]) -> None:
    prefix = "sample row {0}".format(index)
    for field in REQUIRED_SAMPLE_FIELDS:
        if _is_missing(row.get(field, "")):
            errors.append("{0}: missing {1}".format(prefix, field))
    category = _normalize(row.get("category", ""))
    if category not in EXPECTED_SAMPLE_COUNTS:
        errors.append("{0}: unexpected category {1!r}".format(prefix, row.get("category", "")))
    if not _valid_positive_int(row.get("character count", "")):
        errors.append("{0}: character count must be a positive integer".format(prefix))
    if not _valid_positive_int(row.get("paragraph count", "")):
        errors.append("{0}: paragraph count must be a positive integer".format(prefix))
    if _normalize(row.get("transport", "")) not in TRANSPORT_VALUES:
        errors.append("{0}: transport must be text or image".format(prefix))
    for field in ["emoji sent", "trace visible", "favorability visible", "source display"]:
        if _normalize(row.get(field, "")) not in BOOLEAN_VALUES:
            errors.append("{0}: {1} must be yes/no/n/a".format(prefix, field))
    if not _valid_pass(row.get("pass/fail", "")):
        errors.append("{0}: pass/fail must be Pass".format(prefix))
    screenshot = row.get("screenshot path or reference", "")
    if not _resolve_evidence_path(screenshot, repo_root, evidence_file):
        errors.append("{0}: screenshot file does not exist: {1}".format(prefix, screenshot))


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
            "errors": ["evidence file does not exist: {0}".format(evidence_path)],
        }

    with open(evidence_file, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    sample_rows = _table_rows(lines, SAMPLE_HEADERS)
    before_after_rows = _table_rows(lines, BEFORE_AFTER_HEADERS)

    if len(sample_rows) != sum(EXPECTED_SAMPLE_COUNTS.values()):
        errors.append("expected 12 sample rows, found {0}".format(len(sample_rows)))
    if len(before_after_rows) < 5:
        errors.append("expected at least 5 before/after rows, found {0}".format(len(before_after_rows)))

    category_counts = Counter(_normalize(row.get("category", "")) for row in sample_rows)
    for category, expected_count in EXPECTED_SAMPLE_COUNTS.items():
        actual = category_counts.get(category, 0)
        if actual != expected_count:
            errors.append("category {0!r}: expected {1}, found {2}".format(category, expected_count, actual))

    for index, row in enumerate(sample_rows, 1):
        _validate_sample_row(row, root, evidence_file, index, errors)
    for index, row in enumerate(before_after_rows, 1):
        _validate_before_after_row(row, root, evidence_file, index, errors)

    return {
        "ok": not errors,
        "sample_rows": len(sample_rows),
        "before_after_rows": len(before_after_rows),
        "category_counts": dict(category_counts),
        "errors": errors,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Arteta personality manual acceptance evidence.")
    parser.add_argument(
        "evidence",
        nargs="?",
        default="Docs/dev/personality-response-manual-evidence.md",
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
        print("manual evidence validation {0}".format(status))
        print("sample rows: {0}".format(result["sample_rows"]))
        print("before/after rows: {0}".format(result["before_after_rows"]))
        for error in result["errors"]:
            print("- {0}".format(error))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
