# Agent Progress Long-Form Manual Evidence

Date: 2026-07-13

Task: `Docs/tasks/arteta_agent_react_longform_integrated_plan.md`

This file is the operator-facing evidence sheet for the manual QQ acceptance items that cannot be proven by local unit tests, fixture evaluation, or ECS smoke tests.

Do not fill this table with generated fixture output. Each row must come from a real post-deployment QQ interaction or an operator-provided screenshot.

## Required Live QQ Samples

Acceptance requires 12 real replies after deploying commit `59357c7` or a later commit that includes it.

| # | Scenario | User input summary | Screenshot path or reference | Progress sequence | Real tool order | Final answer structure and length | Transport | Reporter closed before final reply | Internal parameter leak | Pass/Fail | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | One-word greeting |  |  |  |  |  |  |  |  |  |  |
| 2 | Short football opinion |  |  |  |  |  |  |  |  |  |  |
| 3 | Image or meme explanation |  |  |  |  |  |  |  |  |  |  |
| 4 | Latest injury |  |  |  |  |  |  |  |  |  |  |
| 5 | Transfer news |  |  |  |  |  |  |  |  |  |  |
| 6 | Math short question |  |  |  |  |  |  |  |  |  |  |
| 7 | Algorithm question |  |  |  |  |  |  |  |  |  |  |
| 8 | Document summary |  |  |  |  |  |  |  |  |  |  |
| 9 | Group memory |  |  |  |  |  |  |  |  |  |  |
| 10 | Explicit concise request |  |  |  |  |  |  |  |  |  |  |
| 11 | Tool timeout fallback |  |  |  |  |  |  |  |  |  |  |
| 12 | Admin confirmation tool |  |  |  |  |  |  |  |  |  |  |

## Before/After Screenshot Evidence

The task plan asks for visual before/after evidence. Because old production behavior cannot be recreated reliably from the current code, the "before" column must use screenshots captured before this change or operator-provided historical screenshots.

| Item | Before screenshot | After screenshot | What changed | Pass/Fail | Notes |
| --- | --- | --- | --- | --- | --- |
| Progress during long-running current-news reply |  |  |  |  |  |
| Progress during math tool reply |  |  |  |  |  |
| Progress during image/meme explanation |  |  |  |  |  |
| Short input default expanded reply |  |  |  |  |  |
| Explicit concise request remains concise |  |  |  |  |  |

## Acceptance Rules

- Progress messages use only `[Agent]`, `[Plan]`, `[Action]`, `[Observation]`, and `[Confirmation]`.
- Progress messages do not contain emoji, `[Thought]`, tool argument values, URLs with query parameters, user IDs, group IDs, prompt text, raw tool results, or raw exception bodies.
- Progress messages are native QQ text and do not appear inside the final reply image/card.
- Final replies do not include progress tags, hidden trace details, raw tool markers, or forced favorability markers.
- Short inputs default to expanded replies unless the user explicitly asks for a concise answer.
- Math, algorithm, code, document, and tactical/detail requests include method, key steps, validation, and answer where applicable.
- The final reply is sent only after delayed progress and heartbeat tasks are closed.

## Current Status

Local tests and ECS smoke are complete for commit `59357c7`, and deployment evidence is recorded in `Docs/dev/agent-progress-longform.md`.

This manual sheet is intentionally blank until an operator records real QQ observations and screenshot paths. The full task should not be marked complete while any row above is blank or failed.
