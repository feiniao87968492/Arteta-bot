# Agent Progress And Long-Form Replies

Date: 2026-07-13

Task plan: `Docs/tasks/arteta_agent_react_longform_integrated_plan.md`

## Runtime Progress

The Agent Registry path now emits sanitized progress events through an explicit observer chain:

```text
arteta_chat.py
-> run_agent_loop(progress_observer=...)
-> AgentRequest.progress_observer
-> run_runtime_loop_from_state(...)
-> AgentRuntimeRunner(progress_observer=...)
```

Progress is formatted and sent by `plugins/arteta_agent/progress/`:

- `models.py` defines lifecycle events and sanitized tool-call metadata.
- `formatter.py` turns events into native QQ text with `[Agent]`, `[Plan]`, `[Action]`, `[Observation]`, and `[Confirmation]`.
- `reporter.py` applies initial delay, dedupe, throttling, max-message limits, one-shot tool heartbeat, one-shot synthesis heartbeat, and close cancellation.

Progress messages are not appended to `AgentState.messages`, not stored in ChromaDB, not added to daily message history, not rendered into final cards, and do not trigger favorability or mood-emoji handling.

## Long-Form Reply Policy

Default reply policy is now expanded unless the user explicitly asks for a short answer or the runtime is in a controlled exception state such as confirmation, tool failure, safety refusal, or no-reply.

The core policy lives in `plugins/arteta_agent/response/length_policy.py`:

- short input defaults to `expanded`;
- explicit “简短 / 一句话 / 只给答案 / 不用解释” switches to `concise`;
- math, algorithm, code, tactics, documents, and explicit detail requests switch to `deep`;
- generated style constraints reject fixed action openings and repeated persona filler.

`plugins/arteta_agent/prompts.py` also removes the old “简单问题 1-3 句 / 梗图 120 字以内” rules. Dashboard Bot Chat uses the same centralized prompt default.

## Transport

QQ Agent replies use `choose_reply_transport(...)` based on final output content:

- normal final replies render as images in QQ, including short plain replies;
- code, formulas, tables, style tags, long structured content, and image artifacts route to image rendering.

Input length no longer forces text or compact mode. Progress updates, timeout/error notices, permission confirmation prompts, and `[NO_REPLY]` silence remain outside the final reply renderer.

## Behavior Policy And Environment

Supported policy prefixes now include:

```text
progress.*
reply.*
```

Useful runtime keys:

```text
ARTETA_AGENT_PROGRESS_ENABLED=true
ARTETA_AGENT_PROGRESS_INITIAL_DELAY=0.8
ARTETA_AGENT_PROGRESS_MIN_INTERVAL=1.8
ARTETA_AGENT_PROGRESS_HEARTBEAT=12.0
ARTETA_AGENT_SYNTHESIS_HEARTBEAT=10.0
ARTETA_AGENT_PROGRESS_MAX_MESSAGES=9
```

Policy examples:

```text
progress.enabled=false
progress.show_observations=false
reply.default_detail_mode=expanded
```

## Verification

Focused local verification:

```powershell
python -m pytest tests\test_arteta_agent_progress_models.py tests\test_arteta_agent_progress_formatter.py tests\test_arteta_agent_progress_reporter.py tests\test_arteta_agent_runtime_progress.py tests\test_arteta_agent_long_form_policy.py tests\test_arteta_agent_response_style.py tests\test_arteta_agent_response_transport.py tests\test_arteta_agent_registry.py tests\test_arteta_chat_commands.py tests\test_arteta_prompt_style.py tests\test_recent_group_context.py -q
# 275 passed

python -m pytest tests -q
# 695 passed

python tools\verify_features.py --suite chat --json-only
# 4 passed

python tools\verify_features.py --suite agent_loop --json-only
# 14 passed

python -m compileall -q bot.py plugins tests tools dashboard
git diff --check
```

## ECS Deployment

Deployed commit:

```text
59357c7 feat: add agent progress and expanded replies
```

Deployment evidence:

```text
archive: /tmp/arteta_agent_react_longform_59357c7.tar.gz
backup: /opt/arteta_bot/backups/react_longform_59357c7_20260713183658
services: arteta_bot RUNNING pid 6646; arteta_dashboard RUNNING pid 6650
```

Remote smoke:

```text
./venv/bin/python tools/verify_features.py --suite chat --json-only
4 passed, report /opt/arteta_bot/artifacts/verify/20260713-183715/report.json

./venv/bin/python tools/verify_features.py --suite agent_loop --json-only
14 passed, report /opt/arteta_bot/artifacts/verify/20260713-183715/report.json

./venv/bin/python tools/verify_features.py --suite agent_registry --suite agent_permissions --json-only
14 passed, report /opt/arteta_bot/artifacts/verify/20260713-183759/report.json
```

Post-restart log health:

```text
tail -120 logs/arteta_bot.log | grep -E 'ERROR|CRITICAL|Traceback'
# no matches
```

## Manual Acceptance Gate

The task plan still requires operator-provided live QQ evidence before full closure:

- 12 end-to-end QQ samples covering one-word greeting, short football opinion, image/meme explanation, latest injury, transfer news, math, algorithm, document summary, group memory, explicit concise request, tool timeout fallback, and admin confirmation tool.
- Each sample must record the Progress sequence, real tool call order, final answer structure/length, no parameter leaks, Reporter close behavior, and final text/image transport.
- Before/after screenshots must come from real QQ captures or operator-provided historical screenshots.

Use `Docs/dev/agent-progress-longform-manual-evidence.md` as the evidence sheet for those observations.

Automated fixtures, local tests, and ECS smoke are not substitutes for those live screenshots.

Manual evidence can be checked with:

```bash
python tools\validate_agent_progress_longform_manual_evidence.py --json
python tools\verify_features.py --suite agent_progress_manual --json-only
```

These commands are expected to fail while the evidence sheet still contains blank rows. The suite is intentionally explicit-only and is not part of `core` or `all`.
