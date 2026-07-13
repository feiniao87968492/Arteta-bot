import argparse
import csv
import os
import sys
from datetime import date
from typing import Dict, List, Optional


SAMPLE_COLUMNS = [
    "category",
    "user_input_summary",
    "screenshot",
    "first_sentence",
    "character_count",
    "paragraph_count",
    "emoji_sent",
    "transport",
    "trace_visible",
    "favorability_visible",
    "source_display",
    "pass_fail",
    "notes",
]

BEFORE_AFTER_COLUMNS = [
    "item",
    "before_screenshot",
    "after_screenshot",
    "what_changed",
    "pass_fail",
    "notes",
]

SAMPLE_TEMPLATE_CATEGORIES = [
    "daily chat",
    "daily chat",
    "daily chat",
    "meme/image",
    "meme/image",
    "football opinion",
    "football opinion",
    "latest news",
    "latest news",
    "tactical deep dive",
    "tactical deep dive",
    "Trace query",
]

BEFORE_AFTER_TEMPLATE_ITEMS = [
    "Short plain reply",
    "Meme/image reply",
    "Long tactical reply",
    "Current news reply",
    "Explicit Trace query",
]


def _read_csv(path: str, required_columns: List[str]) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        missing = [column for column in required_columns if column not in fieldnames]
        if missing:
            raise ValueError("{0} missing column(s): {1}".format(path, ", ".join(missing)))
        return [{column: row.get(column, "") for column in required_columns} for row in reader]


def _write_csv(path: str, columns: List[str], rows: List[Dict[str, str]]) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def write_template_csvs(output_dir: str) -> Dict[str, str]:
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    samples_path = os.path.join(output_dir, "samples.csv")
    before_after_path = os.path.join(output_dir, "before_after.csv")
    sample_rows = []
    for category in SAMPLE_TEMPLATE_CATEGORIES:
        row = {column: "" for column in SAMPLE_COLUMNS}
        row["category"] = category
        sample_rows.append(row)
    before_after_rows = []
    for item in BEFORE_AFTER_TEMPLATE_ITEMS:
        row = {column: "" for column in BEFORE_AFTER_COLUMNS}
        row["item"] = item
        before_after_rows.append(row)
    _write_csv(samples_path, SAMPLE_COLUMNS, sample_rows)
    _write_csv(before_after_path, BEFORE_AFTER_COLUMNS, before_after_rows)
    return {
        "samples_csv": os.path.abspath(samples_path),
        "before_after_csv": os.path.abspath(before_after_path),
    }


def _cell(value: object) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text.replace("|", "/")


def _sample_table(samples: List[Dict[str, str]]) -> str:
    lines = [
        "| # | Category | User input summary | Screenshot path or reference | First sentence | Character count | Paragraph count | Emoji sent | Transport | Trace visible | Favorability visible | Source display | Pass/Fail | Notes |",
        "| --- | --- | --- | --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, row in enumerate(samples, 1):
        lines.append(
            "| {index} | {category} | {input} | {screenshot} | {first} | {chars} | {paragraphs} | {emoji} | {transport} | {trace} | {favorability} | {source} | {pass_fail} | {notes} |".format(
                index=index,
                category=_cell(row.get("category")),
                input=_cell(row.get("user_input_summary")),
                screenshot=_cell(row.get("screenshot")),
                first=_cell(row.get("first_sentence")),
                chars=_cell(row.get("character_count")),
                paragraphs=_cell(row.get("paragraph_count")),
                emoji=_cell(row.get("emoji_sent")),
                transport=_cell(row.get("transport")),
                trace=_cell(row.get("trace_visible")),
                favorability=_cell(row.get("favorability_visible")),
                source=_cell(row.get("source_display")),
                pass_fail=_cell(row.get("pass_fail")),
                notes=_cell(row.get("notes")),
            )
        )
    return "\n".join(lines)


def _before_after_table(rows: List[Dict[str, str]]) -> str:
    lines = [
        "| Item | Before screenshot | After screenshot | What changed | Pass/Fail | Notes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {item} | {before} | {after} | {changed} | {pass_fail} | {notes} |".format(
                item=_cell(row.get("item")),
                before=_cell(row.get("before_screenshot")),
                after=_cell(row.get("after_screenshot")),
                changed=_cell(row.get("what_changed")),
                pass_fail=_cell(row.get("pass_fail")),
                notes=_cell(row.get("notes")),
            )
        )
    return "\n".join(lines)


def build_manual_evidence_markdown(
    samples_csv: str,
    before_after_csv: str,
    generated_date: Optional[str] = None,
) -> str:
    samples = _read_csv(samples_csv, SAMPLE_COLUMNS)
    before_after = _read_csv(before_after_csv, BEFORE_AFTER_COLUMNS)
    today = generated_date or date.today().isoformat()
    return """# Personality Response Manual Evidence Checklist

Date: {today}

Task: `Docs/tasks/arteta_personality_response_optimization_plan.md`

This file is the operator-facing evidence sheet for the manual acceptance items that cannot be proven by local unit tests, fixture evaluation, or ECS smoke tests.

Do not fill this table with generated fixture output. Each row must come from a real post-deployment QQ interaction or an operator-provided screenshot.

## Required Live QQ Reply Samples

Acceptance requires 12 real replies:

- 3 daily chat replies;
- 2 meme/image replies;
- 2 football opinion replies;
- 2 latest news replies;
- 2 tactical deep dive replies;
- 1 Trace query reply.

For each row, record the exact observation from QQ after the deployed bot replies.

{sample_table}

## Before/After Screenshot Evidence

The task plan also asks for visual before/after evidence. Because old production rendering cannot be recreated from the current code without the original screenshots, the "before" column must use screenshots captured before the optimization or operator-provided historical screenshots.

{before_after_table}

## Manual Acceptance Rules

- `Trace visible` should be `no` for ordinary replies and `yes` only for explicit Trace/debug cases.
- `Favorability visible` should normally be `no`; record `yes` only for level changes, configured threshold hits, explicit query, or admin/debug display.
- `Transport` should be `text` for short plain replies and `image` for code, formulas, tables, long structured content, explicit image requests, or image artifacts.
- Latest news/current fact replies must record whether sources were shown in natural language.
- Any row that shows raw `[grok]`, `markers:`, `【Agent 调度】`, tool arguments, or "信任度无变化" in ordinary user-facing output should fail.
- Screenshot fields must point to real local screenshot files, either relative to the repository root or relative to this evidence file. Use redacted screenshots if raw QQ captures contain private data.

## Validation Command

After filling the table, run:

```powershell
python tools\\validate_personality_manual_evidence.py
python tools\\verify_features.py --suite personality_manual
```

Both commands must pass before the manual acceptance item can be treated as complete.
""".format(
        today=today,
        sample_table=_sample_table(samples),
        before_after_table=_before_after_table(before_after),
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build Arteta personality manual evidence Markdown from CSV files.")
    parser.add_argument("--init-dir", help="Write blank samples.csv and before_after.csv templates to this directory.")
    parser.add_argument("--samples-csv", help="CSV containing the 12 live QQ sample rows.")
    parser.add_argument("--before-after-csv", help="CSV containing before/after screenshot rows.")
    parser.add_argument("--output", help="Markdown output path.")
    args = parser.parse_args(argv)

    if args.init_dir:
        paths = write_template_csvs(args.init_dir)
        print("samples_csv={0}".format(paths["samples_csv"]))
        print("before_after_csv={0}".format(paths["before_after_csv"]))
        return 0
    if not args.samples_csv or not args.before_after_csv or not args.output:
        parser.error("--samples-csv, --before-after-csv, and --output are required unless --init-dir is used")

    markdown = build_manual_evidence_markdown(args.samples_csv, args.before_after_csv)
    with open(args.output, "w", encoding="utf-8") as handle:
        handle.write(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
