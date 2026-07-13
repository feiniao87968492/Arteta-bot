# Personality Response Manual Evidence Checklist

Date: 2026-07-13

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

| # | Category | User input summary | Screenshot path or reference | First sentence | Character count | Paragraph count | Emoji sent | Transport | Trace visible | Favorability visible | Source display | Pass/Fail | Notes |
| --- | --- | --- | --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | daily chat |  |  |  |  |  |  | text/image |  |  |  |  |  |
| 2 | daily chat |  |  |  |  |  |  | text/image |  |  |  |  |  |
| 3 | daily chat |  |  |  |  |  |  | text/image |  |  |  |  |  |
| 4 | meme/image |  |  |  |  |  |  | text/image |  |  |  |  |  |
| 5 | meme/image |  |  |  |  |  |  | text/image |  |  |  |  |  |
| 6 | football opinion |  |  |  |  |  |  | text/image |  |  |  |  |  |
| 7 | football opinion |  |  |  |  |  |  | text/image |  |  |  |  |  |
| 8 | latest news |  |  |  |  |  |  | text/image |  |  |  |  |  |
| 9 | latest news |  |  |  |  |  |  | text/image |  |  |  |  |  |
| 10 | tactical deep dive |  |  |  |  |  |  | text/image |  |  |  |  |  |
| 11 | tactical deep dive |  |  |  |  |  |  | text/image |  |  |  |  |  |
| 12 | Trace query |  |  |  |  |  |  | text/image |  |  |  |  |  |

## Before/After Screenshot Evidence

The task plan also asks for visual before/after evidence. Because old production rendering cannot be recreated from the current code without the original screenshots, the "before" column must use screenshots captured before the optimization or operator-provided historical screenshots.

| Item | Before screenshot | After screenshot | What changed | Pass/Fail | Notes |
| --- | --- | --- | --- | --- | --- |
| Short plain reply |  |  | Should now be native QQ text, not a tall card. |  |  |
| Meme/image reply |  |  | Should be short, not a tactical essay by default. |  |  |
| Long tactical reply |  |  | Should keep readable structure with reduced visual chrome. |  |  |
| Current news reply |  |  | Should show status/source naturally without `[grok]` or raw Trace. |  |  |
| Explicit Trace query |  |  | Should show sanitized trace only when requested. |  |  |

## Manual Acceptance Rules

- `Trace visible` should be `no` for ordinary replies and `yes` only for explicit Trace/debug cases.
- `Favorability visible` should normally be `no`; record `yes` only for level changes, configured threshold hits, explicit query, or admin/debug display.
- `Transport` should be `text` for short plain replies and `image` for code, formulas, tables, long structured content, explicit image requests, or image artifacts.
- Latest news/current fact replies must record whether sources were shown in natural language.
- Any row that shows raw `[grok]`, `markers:`, `【Agent 调度】`, tool arguments, or "信任度无变化" in ordinary user-facing output should fail.
- Screenshot fields must point to real local screenshot files, either relative to the repository root or relative to this evidence file. Use redacted screenshots if raw QQ captures contain private data.

## Validation Command

If you prefer filling CSV files first, generate this Markdown file with:

```powershell
python tools\build_personality_manual_evidence.py --samples-csv artifacts\personality_manual\samples.csv --before-after-csv artifacts\personality_manual\before_after.csv --output Docs\dev\personality-response-manual-evidence.md
```

Required `samples.csv` header:

```csv
category,user_input_summary,screenshot,first_sentence,character_count,paragraph_count,emoji_sent,transport,trace_visible,favorability_visible,source_display,pass_fail,notes
```

Required `before_after.csv` header:

```csv
item,before_screenshot,after_screenshot,what_changed,pass_fail,notes
```

After filling the table, run:

```powershell
python tools\validate_personality_manual_evidence.py
python tools\verify_features.py --suite personality_manual
```

Both commands must pass before the manual acceptance item can be treated as complete. They verify:

- all 12 required sample rows are filled;
- required category counts match the task plan;
- character and paragraph counts are positive integers;
- transport is `text` or `image`;
- pass/fail fields are `Pass`;
- all sample, before, and after screenshot files exist.

`personality_manual` is intentionally not part of the default `core` or `all` verification suites because it depends on operator-provided live QQ screenshots. Run it explicitly when closing this task.

## Current Status

Automated code and ECS smoke acceptance is recorded in `Docs/dev/personality-response-acceptance.md`.

Manual QQ screenshot evidence is still pending until this file is filled with real operator observations.
