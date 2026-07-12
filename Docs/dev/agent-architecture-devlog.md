# Agent Architecture Devlog

## 2026-07-11 - Phase A: Dynamic System Injection Closure

### Scope

- Closed the remaining dynamic `system` message injection paths found in the Agent, QQ chat, Dashboard chat, and algorithm/science fallback paths.
- Kept the phase narrow: no broad file moves and no planner architecture split in this stage.

### Changes

- Moved unavailable web verification data into a non-system `UNTRUSTED_WEB_VERIFICATION_RESULT` user data message.
- Kept forced-tool follow-up guidance as a static system instruction; the dynamic tool name is no longer interpolated into that message.
- Added static QQ and Dashboard chat system prompts. Runtime persona, current time, group/user metadata, recent group context, Chroma memory, football-news context, image/document/web/tool data, and policy snapshots are now appended as untrusted user data messages.
- Changed `/算法` and Dashboard algorithm calls to use static system prompts. Dynamic prompt overrides, subject labels, and user problems are passed as user data.
- Hardened the `pysqlite3` monkey-patch used before ChromaDB imports so incomplete fake or broken modules do not replace stdlib `sqlite3`.

### Compatibility

- Preserved `run_agent_loop` and current tool names.
- Preserved OpenAI-compatible message shape where supported.
- Preserved legacy string-return compatibility around existing tool handlers.
- Did not change ECS deployment process or model/provider configuration in this phase.

### Risk Notes

- The local branch already contained the uncommitted Agent Registry baseline before this phase. The phase commit therefore needs to preserve that baseline to remain runnable from a clean checkout.
- Windows full-suite runs still report existing asyncio/proactor unclosed transport warnings. They do not fail the suite and were present before this phase.
- `tools/verify_features.py --suite agent_loop` still has known routing/planning failures unrelated to this phase:
  - `forces_ui_preference_tool`
  - `forces_reply_body_ui_preference_tool`
  - `allows_llm_to_choose_web_verification_tool`
  - `forces_explicit_memory_tool`

### Verification

- `python -m pytest tests/test_recent_group_context.py tests/dashboard/test_bot_chat.py tests/test_arteta_chat_commands.py tests/test_arteta_memory.py tests/dashboard/test_chroma_service.py -q`
  - Result: `58 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `180 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `448 passed, 2 warnings`.
- `python tools\verify_features.py --suite chat`
  - Result: passed.

### Remaining

- Commit the verified Phase A state.
- Deploy the changed runtime files to ECS.
- Run ECS smoke checks.
- Continue with unified Runtime and `AgentState` after Phase A is deployed.

### ECS Smoke Adjustment

After the initial ECS rollout, the bot and dashboard restarted successfully and `python tools\verify_features.py --suite chat` passed on ECS. Two broader smoke cases exposed verifier issues rather than runtime regressions:

- `agent_registry/web_access_offline` was affected by live GrokSearch environment variables on ECS, so the offline fixture could route through the live Grok branch.
- `agent_registry/permission_gates` still expected the removed legacy `confirmed_tool` bypass to authorize an admin tool.

Verifier fix:

- The offline web smoke now clears GrokSearch and X-fetch environment/module configuration, including NoneBot config lookup, while it runs its fake DuckDuckGo/fetch fixture.
- The permission gate smoke now asserts unconfirmed write/admin calls are rejected and legacy `confirmed_tool` does not bypass confirmation. Confirmed execution remains covered by the pending-action executor cases.

Verification after the fix:

- `python -m pytest tests/test_verify_features.py -q`
  - Result: `7 passed`.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed locally.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `180 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `450 passed, 2 warnings`.

## 2026-07-11 - Phase B Slice: Runtime State and Loop Guard Extraction

### Scope

- Introduced the first real Agent Runtime boundary without changing the public `run_agent_loop` entrypoint.
- Kept routing, provider HTTP, behavior-policy storage, response composition, and parallel execution out of this slice.
- Migrated planner tool execution paths to Runtime where the execution semantics are already stable.

### Changes

- Added `plugins/arteta_agent/runtime/` with:
  - `AgentRunConfig` for round, tool-call, repeat-call, observation, timeout, and initial-tool-stop budgets.
  - `AgentState` / `AgentRunResult` for structured runtime state and stop reasons.
  - `LoopGuard` and canonical `tool_call_signature()` using sorted JSON arguments.
  - `AgentRuntimeRunner` for model calls, tool execution, tool observations, budget checks, timeout handling, and `PermissionRequired` stopping.
- Kept planner compatibility helpers, but routed normal model tool calls and forced tool follow-up through `AgentRuntimeRunner`.
- Routed forced direct tools such as behavior-policy updates, UI preference writes, memory preference writes, science/math tools, and trace display through Runtime initial tool calls.
- Preserved explicit PendingAction confirmation as a direct consume path because it is not a model-planned tool call and must use the stored action ID/args.
- Preserved mood emoji post-processing in planner for now; response splitting is planned for the Response phase.

### Compatibility

- `run_agent_loop` signature is unchanged.
- Existing tool names, schemas, permissions, trace output, artifact marker compatibility, and OpenAI-compatible model-call monkeypatch behavior are unchanged.
- Provider HTTP implementation remains in planner for a later provider-adapter phase.
- The old planner loop body remains as unreachable compatibility code behind an early Runtime return; it will be removed when `planner.py` is reduced in Phase I.

### Risk Notes

- This slice intentionally does not solve multi-intent routing, provider client reuse, SQLite policy migration, persistent audit completion, or parallel-safe tool execution.
- The Runtime still uses planner adapters for model calls and final mood-emoji handling, so planner is not yet a thin compatibility entrypoint.
- Windows full-suite runs still report the pre-existing asyncio/proactor unclosed transport warnings.

### Verification

- `python -m pytest tests/test_arteta_agent_runtime.py -q`
  - Result: `5 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `180 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `455 passed, 2 warnings`.

### Remaining

- Continue Phase C by replacing mutually-exclusive forced routing with structured `RouteDecision` / multi-intent plans.

### ECS Deployment

- Commit deployed: `d5b2dae refactor: introduce agent runtime state`.
- Deployment archive: `/tmp/arteta_phase_b_runtime_d5b2dae.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_b_runtime_20260711184516`.
- Remote `py_compile` passed for `planner.py` and `plugins/arteta_agent/runtime/*.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python -m pytest tests/test_arteta_agent_runtime.py -q`
  - Result: not run on ECS because the production venv does not include `pytest` (`No module named pytest`).
- Remote `py_compile` covered the deployed runtime files; local pytest remains the authoritative unit-test run for this slice.

## 2026-07-11 - Phase C Slice: Structured Routing and Multi-Intent Initial Plans

### Scope

- Added the first structured routing/planning model layer.
- Kept the existing planner forced-route chain in place for single-intent behavior.
- Only enabled the new plan path when a message produces more than one required tool, reducing regression risk.

### Changes

- Added `plugins/arteta_agent/routing/models.py` with `Intent`, `RouteDecision`, and `PlannedToolCall`.
- Added `plugins/arteta_agent/routing/heuristic_router.py` for an initial score-like heuristic router.
- Added `plugins/arteta_agent/planning/models.py` and `plan_builder.py` with `AgentPlan`.
- Added planner adapter code that converts multi-intent required tools into Runtime initial tool calls.
- Covered:
  - remember preference + document read;
  - group-memory lookup + current public fact verification;
  - non-math handling for broad numeric phrases such as date, price, and scoreline;
  - explicit equation routing to math.
- Fixed `tools/verify_features.py` agent-loop fixtures so they use strict schemas compatible with server-side argument validation instead of empty object schemas.

### Compatibility

- Existing single-tool forced routes still use their old detection path.
- Existing tool names and schemas are unchanged.
- The new router currently falls back to `grok_search` for public current football facts when used in a multi-intent plan; existing single-intent policy selection remains in planner.

### Risk Notes

- This is not the final RouteDecision rollout. Planner still contains legacy marker constants and most single-intent `if` branches.
- The new heuristic router intentionally covers only the first acceptance-critical multi-intent combinations. Broader datasets and conflict resolution remain.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `6 passed`.
- `python tools\verify_features.py --suite agent_loop`
  - Result: passed locally.
- `python -m pytest tests/test_arteta_agent_routing.py tests/test_arteta_agent_runtime.py tests/test_arteta_agent_registry.py -q`
  - Result: `191 passed, 2 warnings`.
- `python -m pytest tests/test_verify_features.py -q`
  - Result: `8 passed`.
- `python -m pytest tests -q`
  - Result: `462 passed, 2 warnings`.

### ECS Smoke

- Uploaded the `tools/verify_features.py` schema-fixture fix to ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Deployment

- Commit deployed: `a87891a feat: add structured routing plan models`.
- Deployment archive: `/tmp/arteta_phase_c_routing_a87891a.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_routing_20260711190304`.
- Remote `py_compile` passed for planner, routing, and planning modules.
- Restarted `arteta_bot` and `arteta_dashboard`.

### ECS Smoke After Routing Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### Remaining

- Expand RouteDecision coverage to the rest of the task-book samples.
- Replace single-intent `if ... return` routes with plan construction once coverage is broad enough.

## 2026-07-11 - Phase C Slice: Single Current-Fact Route Plan

### Scope

- Moved the first single-intent route from the legacy forced-web chain into the structured `RouteDecision`/`AgentPlan` path.
- Kept the change deliberately narrow: only `public_current_fact` single-tool plans execute before legacy forced branches.

### Changes

- `routing.heuristic_router` now recognizes ASCII current-football fact samples such as `latest Arsenal transfer news`.
- `planning.plan_builder` now applies `route.public_current_fact.preferred_tool` and rewrites the planned call to `grok_search`, `verify_recent_claim`, or `web_search` with the correct argument shape.
- `planner.run_agent_loop` now executes a single required `public_current_fact` plan through the unified Runtime before the old forced-web branch.
- Other single-intent plans still use the existing forced paths until they receive focused route tests.

### Compatibility

- Default public-current-fact routing remains `grok_search`.
- Existing behavior-policy overrides for `route.public_current_fact.preferred_tool` are preserved.
- Disabled or missing tools are still filtered by planner/runtime before execution, preserving fallback behavior.

### Risk Notes

- `planner.py` still contains the legacy forced-web detection as fallback and for unconverted route cases.
- Broader route scoring and conflict resolution remain open; this slice only closes the current factual football question path that caused GrokSearch routing regressions.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py::test_plan_builder_applies_public_current_fact_route_policy -q`
  - RED before fix: failed because the plan did not contain `verify_recent_claim`.
  - GREEN after fix: `1 passed`.
- `python -m pytest tests/test_arteta_agent_routing.py::test_agent_loop_executes_single_current_fact_plan_before_legacy_forced_web -q`
  - RED before fix: failed because the request fell through to `detect_forced_web_verification_args`.
  - GREEN after fix: `1 passed`.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `8 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_forces_groksearch_for_public_current_transfer_questions tests/test_arteta_agent_registry.py::test_agent_loop_forces_groksearch_for_recent_team_match_questions tests/test_arteta_agent_registry.py::test_agent_loop_uses_behavior_policy_route_for_public_current_questions tests/test_arteta_agent_registry.py::test_agent_loop_falls_back_to_grok_when_route_policy_tool_is_unavailable tests/test_arteta_agent_registry.py::test_agent_loop_does_not_force_web_for_group_local_recent_context tests/test_arteta_agent_registry.py::test_agent_loop_lets_llm_choose_memory_for_yesterday_prediction_score -q`
  - Result: `6 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_provider.py -q`
  - Result: `11 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `495 passed` plus existing Windows asyncio/proactor warnings printed after completion.

### Remaining

- Migrate additional single-intent forced branches only after each has route-level RED/GREEN coverage.
- Continue reducing duplicated route policy logic between planner fallback helpers and `plan_builder`.

### ECS Deployment

- Commit deployed: `1b21f5d refactor: route current facts through structured plan`.
- Deployment archive: `/tmp/arteta_phase_c_single_current_fact_1b21f5d.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_single_current_fact_20260711232500`.
- Remote `py_compile` passed for `planner.py`, routing/planning modules, and routing tests.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Single Current-Fact Route Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-11 - Phase C Slice: Current-Fact Plan Builder Helper

### Scope

- Reduced duplicated public-current-fact route policy logic in `planner.py`.
- Kept legacy forced-web fallback behavior but made it call the planning layer for tool selection and argument encoding.

### Changes

- Added `build_public_current_fact_planned_call(...)` in `planning.plan_builder`.
- The helper applies `route.public_current_fact.preferred_tool`, respects disabled tools, accepts a tool-availability callback, and returns a structured `PlannedToolCall`.
- `planner.run_agent_loop` now uses this helper for the remaining forced-web fallback path.
- Removed planner-local `_public_current_fact_route_tool`, `_route_args_for_public_current_fact`, and `_select_public_current_fact_route_tool`.

### Compatibility

- Existing default fallback order remains `grok_search`, then `verify_recent_claim`, then `web_search`.
- Existing behavior-policy route overrides remain compatible.
- Planner still performs registry/disabled-tool filtering before executing the generated call.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py::test_plan_builder_selects_available_public_current_fact_fallback_tool -q`
  - RED before fix: failed because `build_public_current_fact_planned_call` did not exist.
  - GREEN after fix: `1 passed`.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `9 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_routes_recent_news_to_available_verifier tests/test_arteta_agent_registry.py::test_agent_loop_uses_behavior_policy_route_for_public_current_questions tests/test_arteta_agent_registry.py::test_agent_loop_falls_back_to_grok_when_route_policy_tool_is_unavailable tests/test_arteta_agent_registry.py::test_agent_loop_continues_answering_when_forced_web_verification_is_unavailable -q`
  - Result: `4 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `496 passed, 2 warnings`.

### Remaining

- Continue migrating additional planner-local route helpers only with focused route tests.
- The legacy forced-web detector still lives in planner until the route dataset can cover its remaining Chinese/local-memory edge cases.

### ECS Deployment

- Commit deployed: `5a4e699 refactor: move current fact routing policy to planner plan`.
- Deployment archive: `/tmp/arteta_phase_c_plan_builder_current_fact_5a4e699.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_plan_builder_current_fact_20260711234000`.
- Remote `py_compile` passed for `planner.py`, `planning/plan_builder.py`, and routing tests.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Current-Fact Plan Builder Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-11 - Phase D Slice: Structured Artifact Marker Boundary

### Scope

- Began Response/Artifact split by moving artifact marker extraction out of planner into `agent/response`.
- Closed the security gap where arbitrary tool body text could forge `[GeneratedImage: ...]` style artifact markers.

### Changes

- Added `plugins/arteta_agent/response/artifacts.py`.
- Added `ToolResult.artifacts` as the structured artifact channel.
- Executor now adapts legacy artifact-marker strings into `ToolResult.artifacts` only for known artifact-producing tools:
  - render tools;
  - image generation;
  - link analysis;
  - web/grok verification tools that produce source snapshots.
- Planner artifact collection now reads `ToolResult.artifacts` instead of regexing every tool observation body.
- Added a regression test proving a normal safe-read tool can return forged artifact marker text as data without causing the final answer to include a generated artifact.

### Compatibility

- Existing artifact-producing tools can still return legacy `[RenderedImage: ...]`, `[GeneratedImage: ...]`, and `[LinkSnapshotImage: ...]` markers.
- Existing Grok/link snapshot preservation remains compatible through the executor adapter.

### Risk Notes

- This is not the full response composer split. Planner still appends artifact markers and handles mood emoji post-processing.
- The legacy adapter remains intentionally narrow until tools return fully structured `ToolResult` objects directly.

### Verification

- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_treats_forged_artifact_marker_in_safe_tool_output_as_data tests/test_arteta_agent_registry.py::test_agent_loop_preserves_grok_snapshot_artifact_from_tool_result tests/test_arteta_agent_registry.py::test_agent_loop_preserves_link_snapshot_artifact_after_model_summary -q`
  - Result: `3 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `181 passed, 2 warnings`.
- `python -m pytest tests/test_arteta_agent_routing.py tests/test_arteta_agent_runtime.py -q`
  - Result: `11 passed`.
- `python -m pytest tests -q`
  - Result: `463 passed, 2 warnings`.

### ECS Deployment

- Commit deployed: `2071760 refactor: collect artifacts from tool results`.
- Deployment archive: `/tmp/arteta_phase_d_artifacts_2071760.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_d_artifacts_20260711190950`.
- Remote `py_compile` passed for the deployed planner, executor, result, and response artifact modules.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Artifact Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

### Remaining

- Continue the response split with a dedicated composer for confirmation, degradation, artifact appending, trace formatting, and mood emoji post-processing.
- Keep the current legacy artifact adapter narrow until tools return native structured artifacts directly.

## 2026-07-11 - Phase D Slice: Response Composer Boundary

### Scope

- Added the first dedicated response composer module.
- Moved final artifact appending and Grok trace prefixing out of planner's inline `finish()` closure.
- Kept mood emoji post-processing, confirmation prompts, and degradation copy in existing runtime/planner paths for later response slices.

### Changes

- Added `plugins/arteta_agent/response/composer.py`.
- Added `compose_final_response(...)`, `prefix_trace_markers(...)`, and `trace_has_marker(...)`.
- Planner now calls `compose_final_response(value, artifacts=tool_artifact_markers, trace=trace)` for final response assembly.
- Added `tests/test_arteta_agent_response.py` to pin the response boundary:
  - structured artifacts are appended once;
  - artifact-looking text in the answer body is treated as normal text;
  - `[grok]` prefixing comes from trace markers.

### Compatibility

- Existing `run_agent_loop` behavior is unchanged.
- Existing structured artifact markers still append to final output once.
- Existing Grok trace marker prefix behavior is preserved.
- Planner keeps thin wrapper functions for trace marker helpers to reduce churn in this slice.

### Risk Notes

- This is still not the complete response split. Planner still controls mood emoji forcing and several forced-tool/direct-return paths.
- The composer intentionally does not regex-scan arbitrary answer or tool body text for artifacts; artifacts must come from the structured list passed by runtime/planner.

### Verification

- `python -m pytest tests/test_arteta_agent_response.py -q`
  - Result: `3 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_treats_forged_artifact_marker_in_safe_tool_output_as_data tests/test_arteta_agent_registry.py::test_agent_loop_preserves_grok_snapshot_artifact_from_tool_result tests/test_arteta_agent_registry.py::test_agent_loop_preserves_link_snapshot_artifact_after_model_summary tests/test_arteta_agent_registry.py::test_trace_records_grok_result_marker -q`
  - Result: `4 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `181 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `466 passed, 2 warnings`.

### Remaining

- Move confirmation prompts, stable degradation text, trace block formatting entrypoints, and mood emoji post-processing behind response/runtime adapters.
- Continue keeping artifact trust boundaries structural rather than regexing arbitrary tool text.

### ECS Deployment

- Commit deployed: `023cbaa refactor: extract response composer boundary`.
- Deployment archive: `/tmp/arteta_phase_d_composer_023cbaa.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_d_composer_20260711193000`.
- Remote `py_compile` passed for planner, response composer, and response tests.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Composer Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-11 - Phase D Slice: Planner Artifact Regex Cleanup

### Scope

- Removed remaining planner ownership of artifact marker regex/extraction.
- Kept artifact trust on structured `ToolResult.artifacts` and response composer inputs.

### Changes

- Added a source regression proving `planner.py` no longer imports or defines artifact marker regex helpers.
- Removed `ARTIFACT_MARKER_RE` / `extract_artifact_markers` imports from planner.
- Deleted unreachable forced-tool fallback code that still tried to append artifact markers from plain tool result text.
- Kept `_remember_artifact_markers(...)` because it only collects structured `ToolResult.artifacts`.

### Compatibility

- Existing artifact-producing tools still work through executor legacy adapters and structured `ToolResult.artifacts`.
- Forged artifact markers in arbitrary safe-read tool bodies remain normal text data and are not appended as artifacts.

### Verification

- `python -m pytest tests/test_arteta_agent_response.py::test_planner_no_longer_owns_artifact_marker_extraction_protocol -q`
  - RED before fix: failed because planner still contained `ARTIFACT_MARKER_RE`.
  - GREEN after fix: `1 passed`.
- `python -m pytest tests/test_arteta_agent_response.py -q`
  - Result: `4 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_treats_forged_artifact_marker_in_safe_tool_output_as_data tests/test_arteta_agent_registry.py::test_agent_loop_preserves_grok_snapshot_artifact_from_tool_result tests/test_arteta_agent_registry.py::test_agent_loop_preserves_link_snapshot_artifact_after_model_summary tests/test_arteta_agent_registry.py::test_agent_loop_forces_document_tool_when_document_is_present -q`
  - Result: `4 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `497 passed, 2 warnings`.

### Remaining

- Move more response-oriented helper wrappers out of planner only after source and behavior tests cover their public compatibility.
- `arteta_chat.py` still has legacy artifact marker parsing for outer QQ message rendering; that is outside the Agent planner boundary and should be audited separately.

### ECS Deployment

- Commit deployed: `cea36ff refactor: remove planner artifact marker parsing`.
- Deployment archive: `/tmp/arteta_phase_d_planner_artifact_cleanup_cea36ff.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_d_planner_artifact_cleanup_20260711235400`.
- Remote `py_compile` passed for `planner.py` and response tests.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Planner Artifact Cleanup Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-11 - Phase D Slice: Mood Emoji Response Finalizer

### Scope

- Moved the runtime mood-emoji finalizer decision and execution wrapper into the response package.
- Kept the existing `send_mood_emoji` tool, permission enforcement, trace recording, and post-reply queue behavior unchanged.
- Did not change neutral/debug policy: policy and trace/debug turns still do not auto-send emoji.

### Changes

- Added `plugins/arteta_agent/response/mood.py`.
- Added `maybe_send_mood_emoji(...)` with explicit dependency injection for:
  - tool lookup;
  - tool execution;
  - group emoji policy lookup.
- Added unit tests in `tests/test_arteta_agent_mood_response.py` for:
  - negative reply fallback sending an emoji when the model skipped the tool;
  - policy/trace operational turns not sending emoji;
  - disabled or already-called emoji tool not sending again.
- Planner's runtime finalizer now delegates to `maybe_send_mood_emoji(...)`.
- Planner keeps compatibility wrappers for old helper names to reduce churn while later cleanup removes unreachable legacy bodies.

### Compatibility

- `run_agent_loop` output remains unchanged.
- Existing `send_mood_emoji` tool schema and permission level remain unchanged.
- Tool execution still goes through `execute_tool_call`, so schema validation, permission checks, trace, and audit behavior are preserved.

### Risk Notes

- The older unreachable mood helper bodies still exist in planner after an early return because the source contains mojibake text that makes broad deletion riskier. They are no longer on the active runtime path and should be cleaned in a later planner-thinning pass.
- This slice does not move permission confirmation messages or degradation text yet.

### Verification

- `python -m pytest tests/test_arteta_agent_mood_response.py -q`
  - Result: `3 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_forces_negative_mood_emoji_when_llm_skips_tool tests/test_arteta_agent_registry.py::test_agent_loop_forces_positive_neutral_mood_emoji_for_non_negative_reply tests/test_arteta_agent_registry.py::test_agent_loop_does_not_force_mood_emoji_after_behavior_policy_query -q`
  - Result: `3 passed`.
- `python -m pytest tests/test_arteta_agent_mood_response.py tests/test_arteta_agent_response.py tests/test_arteta_agent_registry.py -q`
  - Result: `187 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `469 passed, 2 warnings`.

### Remaining

- Continue moving confirmation/degradation copy and trace formatting entrypoints into response adapters.
- Remove unreachable planner legacy response code during the final planner-thinning phase once coverage around all response branches is complete.

### ECS Deployment

- Commit deployed: `b80464f refactor: move mood emoji finalizer to response layer`.
- Deployment archive: `/tmp/arteta_phase_d_mood_b80464f.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_d_mood_20260711200500`.
- Remote `py_compile` passed for planner, response mood module, and mood response tests.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Mood Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase D Slice: Planner Mood Wrapper Cleanup

### Scope

- Removed unreachable inline mood detection and suppression logic left in planner after the mood finalizer moved to `response.mood`.
- Preserved planner wrapper function names for compatibility with existing tests/imports.

### Changes

- Added a source regression proving planner mood wrappers contain only a single delegation return.
- `_should_allow_forced_mood_emoji(...)` now delegates directly to `response.mood.should_allow_forced_mood_emoji`.
- `detect_forced_mood_emoji_args(...)` now delegates directly to `response.mood.detect_forced_mood_emoji_args`.
- Deleted unreachable duplicate mood keyword lists and policy suppression code from planner.

### Compatibility

- Mood sending behavior is unchanged; runtime finalization still calls `maybe_send_mood_emoji(...)`.
- Existing planner wrapper names remain available during the compatibility transition.

### Verification

- `python -m pytest tests/test_arteta_agent_mood_response.py::test_planner_mood_wrappers_do_not_keep_unreachable_inline_logic -q`
  - RED before fix: failed because `_should_allow_forced_mood_emoji` contained four return statements.
  - GREEN after fix: `1 passed`.
- `python -m pytest tests/test_arteta_agent_mood_response.py -q`
  - Result: `4 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_forces_negative_mood_emoji_when_llm_skips_tool tests/test_arteta_agent_registry.py::test_agent_loop_forces_positive_neutral_mood_emoji_for_non_negative_reply tests/test_arteta_agent_registry.py::test_agent_loop_does_not_force_mood_emoji_after_behavior_policy_query -q`
  - Result: `3 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `498 passed, 2 warnings`.

### ECS Deployment

- Commit deployed: `0629235 refactor: remove planner mood wrapper dead code`.
- Deployment archive: `/tmp/arteta_phase_d_mood_wrapper_cleanup_0629235.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_d_mood_wrapper_cleanup_20260712000927`.
- Remote `py_compile` passed for `plugins/arteta_agent/planner.py` and `tests/test_arteta_agent_mood_response.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.

### ECS Smoke After Planner Mood Wrapper Cleanup Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

### Remaining

- Later planner-thinning passes can remove compatibility wrappers once no tests or external code import them directly.

## 2026-07-12 - Phase D Slice: Planner Trace Marker Helper Cleanup

### Scope

- Removed unused trace-marker compatibility wrappers from `planner.py` after marker prefixing moved behind `response.composer`.
- Kept final response behavior unchanged through `compose_final_response(...)`.

### Changes

- Added a source regression proving planner no longer imports or defines `prefix_trace_markers` / `trace_has_marker` helpers.
- Removed planner-local `_trace_has_marker(...)` and `_prefix_trace_markers(...)`.
- Narrowed the planner composer import to `compose_final_response` only.

### Compatibility

- `[grok]` response prefixing still runs through `response.composer.compose_final_response(...)`.
- Trace block rendering still uses `trace.format_trace_block(...)`; this slice only removes unused response marker wrappers.

### Verification

- `python -m pytest tests/test_arteta_agent_response.py::test_planner_no_longer_owns_trace_marker_helpers -q`
  - RED before fix: failed because `planner.py` still imported `prefix_trace_markers` and `trace_has_marker`.
  - GREEN after fix: `1 passed`.
- `python -m pytest tests/test_arteta_agent_response.py -q`
  - Result: `5 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_trace_records_grok_result_marker tests/test_arteta_agent_registry.py::test_agent_loop_records_rounds_and_tool_trace tests/test_arteta_agent_registry.py::test_agent_loop_preserves_grok_snapshot_artifact_from_tool_result tests/test_arteta_agent_registry.py::test_agent_loop_treats_forged_artifact_marker_in_safe_tool_output_as_data -q`
  - Result: `4 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `499 passed, 2 warnings`.

### ECS Deployment

- Commit deployed: `009851f refactor: remove planner trace marker wrappers`.
- Deployment archive: `/tmp/arteta_phase_d_trace_marker_cleanup_009851f.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_d_trace_marker_cleanup_20260712002727`.
- Remote `py_compile` passed for `plugins/arteta_agent/planner.py` and `tests/test_arteta_agent_response.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.

### ECS Smoke After Planner Trace Marker Cleanup Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

### Remaining

- Planner still directly handles trace-request forced routing and calls `format_trace_block(...)`; moving that behind a response/runtime boundary remains a later planner-thinning step.

## 2026-07-12 - Phase D Slice: Trace Response Composer Boundary

### Scope

- Moved trace-response text composition out of `planner.py` and behind `response.composer`.
- Kept the existing trace-request forced tool path unchanged so `show_agent_trace` still appears as a real safe-read tool call.

### Changes

- Added `compose_trace_response(trace)` to `plugins/arteta_agent/response/composer.py`.
- `planner.run_agent_loop(...)` now calls `compose_trace_response(trace)` instead of importing/calling `format_trace_block(...)` directly.
- Added source regression proving planner no longer references `format_trace_block`.

### Compatibility

- Trace formatting still uses `plugins.arteta_agent.trace.format_trace_block(...)` internally.
- Existing fallback text remains `[Agent Trace]\ntools: none`.
- `show_agent_trace` tool behavior and sanitized trace fields are unchanged.

### Verification

- `python -m pytest tests/test_arteta_agent_response.py::test_response_composer_formats_trace_response_with_fallback tests/test_arteta_agent_response.py::test_planner_no_longer_calls_trace_formatter_directly -q`
  - RED before fix: failed because `compose_trace_response` did not exist and planner still imported `format_trace_block`.
  - GREEN after fix: `2 passed`.
- `python -m pytest tests/test_arteta_agent_response.py -q`
  - Result: `7 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_forces_trace_tool_when_user_requests_trace tests/test_arteta_agent_registry.py::test_show_agent_trace_tool_returns_sanitized_trace_block tests/test_arteta_agent_registry.py::test_agent_loop_records_rounds_and_tool_trace tests/test_arteta_agent_registry.py::test_trace_records_grok_result_marker -q`
  - Result: `4 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `501 passed, 2 warnings`.

### ECS Deployment

- Commit deployed: `7f74e02 refactor: compose trace response outside planner`.
- Deployment archive: `/tmp/arteta_phase_d_trace_response_7f74e02.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_d_trace_response_20260712004100`.
- Remote `py_compile` passed for `plugins/arteta_agent/planner.py`, `plugins/arteta_agent/response/composer.py`, and `tests/test_arteta_agent_response.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.

### ECS Smoke After Trace Response Composer Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

### Remaining

- Planner still owns the decision to force `show_agent_trace`; moving that route decision into structured planning remains separate from response composition.

## 2026-07-12 - Phase C/D Slice: Structured Trace Route Plan

### Scope

- Moved explicit trace/debug requests from a planner keyword branch into `RouteDecision` / `AgentPlan`.
- Preserved the important compatibility behavior: trace requests execute `show_agent_trace` as a real safe-read tool and return the sanitized trace directly without a follow-up LLM call.

### Changes

- Router now emits an `agent_trace` intent, required `show_agent_trace` call, and `direct_trace_response` constraint for explicit trace/debug requests.
- `AgentPlan` now carries `constraints` copied from `RouteDecision`.
- `plan_builder` sets `execute_single_required_tool` for `public_current_fact`, preserving the existing single-tool current-fact execution path after planner stopped checking route intents directly.
- Planner builds the initial `RouteDecision`/`AgentPlan` once, executes available planned calls, and uses `direct_trace_response` to stop after initial tools and compose the trace response.
- Removed the `if wants_trace_tool(state)` forced branch from `run_agent_loop`.

### Compatibility

- Existing `show_agent_trace` tool name, permission, trace fields, and output formatting are unchanged.
- Public-current-fact single-tool route behavior remains enabled through plan constraints.
- Missing or disabled tools still prevent the planned call from executing.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py::test_plan_builder_routes_trace_requests_with_direct_response_constraint -q`
  - RED before fix: failed because router did not emit `agent_trace`.
  - GREEN after fix: passed.
- `python -m pytest tests/test_arteta_agent_routing.py::test_planner_uses_structured_plan_instead_of_trace_keyword_branch -q`
  - RED before fix: failed because planner still had `if wants_trace_tool(state)`.
  - GREEN after fix: passed.
- `python -m pytest tests/test_arteta_agent_routing.py::test_plan_builder_routes_trace_requests_with_direct_response_constraint tests/test_arteta_agent_routing.py::test_planner_uses_structured_plan_instead_of_trace_keyword_branch tests/test_arteta_agent_registry.py::test_agent_loop_forces_trace_tool_when_user_requests_trace tests/test_arteta_agent_routing.py::test_agent_loop_executes_single_current_fact_plan_before_legacy_forced_web -q`
  - Result: `4 passed`.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `11 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_forces_groksearch_for_public_current_transfer_questions tests/test_arteta_agent_registry.py::test_agent_loop_uses_behavior_policy_route_for_public_current_questions tests/test_arteta_agent_registry.py::test_agent_loop_does_not_force_web_for_casual_future_or_current_words tests/test_arteta_agent_routing.py::test_agent_loop_executes_single_current_fact_plan_before_legacy_forced_web -q`
  - Result: `4 passed`.
- `python -m pytest tests/test_arteta_agent_routing.py tests/test_arteta_agent_response.py -q`
  - Result: `18 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `503 passed, 2 warnings`.

### ECS Deployment

- Commit deployed: `ce2332d refactor: route trace requests through agent plan`.
- Deployment archive: `/tmp/arteta_phase_c_trace_plan_ce2332d.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_trace_plan_20260712010048`.
- Remote `py_compile` passed for planner, planning models/builder, routing heuristic, and routing tests.
- Restarted `arteta_bot` and `arteta_dashboard`.

### ECS Smoke After Structured Trace Route Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

### Remaining

- `wants_trace_tool(...)` and `TRACE_REQUEST_MARKERS` are now compatibility/dead planner symbols; a later cleanup can remove them after checking direct imports.
- Additional planner forced branches for UI, memory, document, link, web, and science still need separate RouteDecision/Plan migrations.

## 2026-07-12 - Phase C/D Slice: Remove Dead Planner Trace Helpers

### Scope

- Removed the compatibility/dead trace keyword helper symbols left after structured trace routing landed.

### Changes

- Deleted `TRACE_REQUEST_MARKERS` from `planner.py`.
- Deleted `wants_trace_tool(...)` from `planner.py`.
- Strengthened the routing source regression to prove planner no longer owns the trace route marker set or helper.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py::test_planner_uses_structured_plan_instead_of_trace_keyword_branch -q`
  - RED before fix: failed because `def wants_trace_tool` still existed.
  - GREEN after fix: `1 passed`.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `11 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_forces_trace_tool_when_user_requests_trace tests/test_arteta_agent_registry.py::test_agent_loop_records_rounds_and_tool_trace -q`
  - Result: `2 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `503 passed, 2 warnings`.

### ECS Deployment

- Commit deployed: `052e41c refactor: remove dead planner trace helpers`.
- Deployment archive: `/tmp/arteta_phase_c_trace_helper_cleanup_052e41c.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_trace_helper_cleanup_20260712010919`.
- Remote `py_compile` passed for `plugins/arteta_agent/planner.py` and `tests/test_arteta_agent_routing.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.

### ECS Smoke After Trace Helper Cleanup Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

### Remaining

- Additional planner-local marker sets for UI, memory, document, link, web, and science still need separate routing-module migrations.

## 2026-07-12 - Phase C Slice: Extract UI Preference Detector

### Scope

- Moved UI preference argument detection out of `planner.py` and into the routing layer.
- Kept the existing forced `update_ui_preference` execution branch unchanged for this slice.

### Changes

- Added `plugins/arteta_agent/routing/contextual_tools.py`.
- Moved the UI style/font-scale detector to `detect_ui_preference_args(...)`.
- Planner now imports and calls the routing detector instead of defining `detect_forced_ui_preference_args(...)`.
- Added source regression proving planner no longer defines the UI detector helpers.

### Compatibility

- Existing UI preference behavior is unchanged, including `reply_body`, trace title/tool/detail targets, color, bold, font size, and font scale extraction.
- `update_ui_preference` remains a registered safe-write tool and still executes through the existing runtime path.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py::test_contextual_tools_detects_ui_preference_args_for_reply_body_style tests/test_arteta_agent_routing.py::test_planner_no_longer_defines_ui_preference_detector -q`
  - RED before fix: failed because `routing.contextual_tools` did not exist and planner still defined the detector.
  - GREEN after fix: `2 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_forces_ui_preference_tool_for_trace_color_request tests/test_arteta_agent_registry.py::test_agent_loop_forces_ui_preference_tool_for_rich_trace_style tests/test_arteta_agent_registry.py::test_agent_loop_forces_ui_preference_tool_for_five_times_trace_style tests/test_arteta_agent_registry.py::test_agent_loop_forces_ui_preference_tool_for_five_times_reply_body_style -q`
  - Result: `4 passed`.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `13 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `505 passed, 2 warnings`.

### ECS Deployment

- Commit deployed: `85258fd refactor: extract ui preference detector`.
- Deployment archive: `/tmp/arteta_phase_c_ui_detector_85258fd.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_ui_detector_20260712011900`.
- Remote `py_compile` passed for `plugins/arteta_agent/planner.py`, `plugins/arteta_agent/routing/contextual_tools.py`, and `tests/test_arteta_agent_routing.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.

### ECS Smoke After UI Detector Extract Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

### Remaining

- The planner still owns the forced execution branch for `update_ui_preference`; the next routing slice can convert this detector output into a structured plan call.

## 2026-07-12 - Phase C Slice: Structured UI Preference Plan

### Scope

- Migrated UI preference requests from a planner forced branch into `RouteDecision` / `AgentPlan`.
- Preserved legacy behavior where UI preference updates execute the registered tool and return the tool result directly without asking the model for follow-up text.

### Changes

- Router now emits a `ui_preference` intent with required `update_ui_preference` planned call.
- UI plans set `execute_single_required_tool` and `direct_tool_response` constraints.
- Planner now uses `direct_tool_response` to stop after initial planned tools and return the tool result.
- Removed the planner-local `forced_ui_args` branch.

### Compatibility

- UI preference detection and arguments stay unchanged from the previous detector-extraction slice.
- Requests like `下次回复文字标红、加粗、放大五倍` still update `reply_body` rather than being treated as generic memory.
- The tool remains permission-checked by the registry executor.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py::test_plan_builder_routes_ui_preference_requests_as_required_tool tests/test_arteta_agent_routing.py::test_planner_no_longer_has_forced_ui_preference_branch -q`
  - RED before fix: failed because router did not emit `ui_preference` and planner still had `forced_ui_args`.
  - GREEN after fix: `2 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_forces_ui_preference_tool_for_trace_color_request tests/test_arteta_agent_registry.py::test_agent_loop_forces_ui_preference_tool_for_rich_trace_style tests/test_arteta_agent_registry.py::test_agent_loop_forces_ui_preference_tool_for_five_times_trace_style tests/test_arteta_agent_registry.py::test_agent_loop_forces_ui_preference_tool_for_five_times_reply_body_style -q`
  - Result: `4 passed`.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `15 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `507 passed, 2 warnings`.

### ECS Deployment

- Commit deployed: `60e0bf4 refactor: route ui preferences through agent plan`.
- Deployment archive: `/tmp/arteta_phase_c_ui_plan_60e0bf4.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_ui_plan_20260712012841`.
- Remote `py_compile` passed for planner, routing heuristic, and routing tests.
- Restarted `arteta_bot` and `arteta_dashboard`.

### ECS Smoke After Structured UI Preference Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

### Remaining

- Memory, document, link, web, and science forced branches still need separate structured-plan migration.

## 2026-07-11 - Phase E Slice: OpenAI-Compatible Provider Adapter

### Scope

- Began the Provider split by moving planner's direct OpenAI-compatible HTTP request/response handling behind provider modules.
- Added a shared AsyncClient lifecycle boundary for the main agent provider path.
- Preserved the public `call_llm_with_tools(...)` function because tests, verifier smoke, and existing monkeypatch fixtures still use it as the compatibility seam.

### Changes

- Added `plugins/arteta_agent/providers/http_client.py`.
- Added `plugins/arteta_agent/providers/openai_compatible.py`.
- Added `OpenAICompatibleProvider`, `ProviderCapabilities`, `ProviderResponseError`, and `parse_chat_response(...)`.
- Planner now uses `OpenAICompatibleProvider(client=get_shared_async_client(), ...)` instead of creating `httpx.AsyncClient` inside `call_llm_with_tools`.
- Per-request timeout is passed to provider `.chat(...)`; the shared client itself is no longer recreated per request.
- Existing provider response parsing behavior remains:
  - content and role are returned;
  - `tool_calls` are preserved;
  - `reasoning_content` is preserved for DeepSeek/OpenAI-compatible thinking-mode compatibility;
  - non-JSON and malformed responses raise `ProviderResponseError`.

### Compatibility

- Existing `run_agent_loop` and `call_llm_with_tools` signatures are unchanged.
- Existing tool schema exposure and `tool_choice=auto` behavior are unchanged.
- The old `planner.ProviderResponseError` import path remains valid by re-exporting the provider error class.
- Tests that previously monkeypatched `planner.httpx.AsyncClient` now inject through the shared client factory, matching the new provider boundary.

### Risk Notes

- This is only the first Provider slice. Activation, web tools, image/vision, daily/weekly, and dashboard algorithm calls still create their own HTTP clients.
- Retry/backoff, provider capability branching beyond the current flags, and application shutdown hook integration remain for later slices.
- The shared client default currently uses `httpx.AsyncClient()` and per-request timeout on `.post(...)`, which preserves request behavior while enabling reuse.

### Verification

- `python -m pytest tests/test_arteta_agent_provider.py -q`
  - Result: `3 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_planner_uses_chat_temperature tests/test_arteta_agent_registry.py::test_agent_planner_uses_configurable_llm_timeout tests/test_arteta_agent_registry.py::test_agent_planner_omits_tool_fields_when_no_tools_are_visible tests/test_arteta_agent_registry.py::test_agent_planner_reports_non_json_provider_response -q`
  - Result: `4 passed`.
- `python -m pytest tests/test_arteta_agent_provider.py tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `472 passed, 2 warnings`.

### Remaining

- Wire activation to the same provider/client infrastructure.
- Add application shutdown integration for `close_shared_async_client()`.
- Add retry/backoff and capability-based message encoding tests.
- Continue removing direct provider HTTP code from planner and other business modules.

### ECS Deployment

- Commit deployed: `6f3de84 refactor: add openai compatible provider adapter`.
- Deployment archive: `/tmp/arteta_phase_e_provider_6f3de84.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_e_provider_20260711202500`.
- Remote `py_compile` passed for planner, provider modules, and provider tests.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Provider Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-11 - Phase E Slice: Activation Uses Provider Client

### Scope

- Reused the provider adapter and shared AsyncClient for activation LLM calls.
- Preserved the activation public APIs and fail-closed behavior.
- Kept the existing activation prompt/message builder unchanged.

### Changes

- `plugins/arteta_agent/activation.py` no longer creates its own `httpx.AsyncClient`.
- `call_activation_llm(...)` now uses `OpenAICompatibleProvider(client=get_shared_async_client(), ...)`.
- `OpenAICompatibleProvider.chat(...)` now accepts `extra_payload` so activation can pass:
  - `max_tokens=80`;
  - `response_format={"type": "json_object"}`.
- Added provider tests for extra payload merging and activation using the shared client.

### Compatibility

- `decide_activation_with_agent(...)` signature and `llm_call` injection remain unchanged.
- Activation still returns false on missing API key, invalid JSON, and provider errors.
- The request payload keeps `temperature=0`, `max_tokens=80`, and JSON response format.

### Risk Notes

- This slice does not change activation routing heuristics or fail-open/fail-closed policy.
- Shared provider shutdown is still a pending lifecycle integration task.
- Other modules outside activation and planner still have independent HTTP clients.

### Verification

- `python -m pytest tests/test_arteta_agent_provider.py -q`
  - Result: `5 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_activation_judge_parses_json_decision tests/test_arteta_agent_registry.py::test_activation_judge_fails_closed_on_invalid_or_error -q`
  - Result: `2 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `488 passed` plus existing Windows asyncio/proactor warnings printed after completion.

### ECS Deployment

- Commit deployed: `a71aabf refactor: reuse provider client for activation`.
- Deployment archive: `/tmp/arteta_phase_e_activation_a71aabf.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_e_activation_20260711203000`.
- Remote `py_compile` passed for activation, provider adapter, and provider tests.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Activation Provider Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-11 - Phase E Slice: Provider Client Shutdown Hook

### Scope

- Connected the shared OpenAI-compatible provider HTTP client to the NoneBot application shutdown lifecycle.

### Changes

- `bot.py` imports `close_shared_async_client`.
- The NoneBot driver now registers `driver.on_shutdown(close_shared_async_client)` after initialization.

### Compatibility

- `run_agent_loop` and provider APIs are unchanged.
- The hook only closes the shared client on application shutdown; tests still use `set_shared_async_client_factory(...)` injection.

### Verification

- `python -m pytest tests/test_arteta_agent_provider.py::test_bot_entry_registers_provider_client_shutdown_hook -q`
  - RED before fix: failed because `bot.py` did not reference `close_shared_async_client`.
  - GREEN after fix: `1 passed`.
- `python -m pytest tests/test_arteta_agent_provider.py -q`
  - Result: `6 passed`.
- `python -m pytest tests/test_arteta_agent_provider.py tests/test_arteta_agent_registry.py -q`
  - Result: `190 passed, 2 warnings`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `488 passed` plus existing Windows asyncio/proactor warnings printed after completion.

### ECS Deployment

- Commit deployed: `397fbc9 refactor: close provider client on shutdown`.
- Follow-up docs commit: `14bbf5b docs: record provider shutdown deployment`.
- Deployment archive: `/tmp/arteta_phase_e_provider_shutdown_397fbc9.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_e_provider_shutdown_20260711215200`.
- Remote `py_compile` passed for `bot.py` and `tests/test_arteta_agent_provider.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Provider Shutdown Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-11 - Phase E Slice: Fixed Provider Adapter Protocol

### Scope

- Removed the remaining runtime `inspect.signature(...)` compatibility branch from the planner provider call path.
- Kept the public `call_llm_with_tools(...)` compatibility entrypoint, but made `_call_llm_with_policy(...)` call the fixed OpenAI-compatible adapter protocol directly.

### Changes

- `planner._call_llm_with_policy(...)` now always passes `api_url`, `allowed_permissions`, `disabled_tools`, `temperature`, and `request_timeout` as explicit keyword arguments.
- Removed the unused `inspect` import from `planner.py`.
- Updated local pytest fakes and `tools/verify_features.py` smoke fakes to implement the fixed provider protocol.
- Added a source regression test proving `planner.py` no longer calls `inspect.signature(call_llm_with_tools)`.

### Compatibility

- Production behavior remains OpenAI-compatible and DeepSeek-compatible through the existing provider adapter.
- Existing external callers can still call `planner.call_llm_with_tools(...)` with its current signature.
- Test and smoke fixtures were updated rather than keeping production runtime reflection for legacy fake signatures.

### Verification

- `python -m pytest tests/test_arteta_agent_provider.py::test_planner_provider_call_uses_fixed_adapter_protocol -q`
  - RED before fix: failed because `planner.py` still contained `inspect.signature(call_llm_with_tools)`.
  - GREEN after fix: `1 passed`.
- `python -m pytest tests/test_arteta_agent_provider.py tests/test_arteta_agent_routing.py tests/test_arteta_agent_registry.py -q`
  - Result: `197 passed, 2 warnings`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_provider.py tests/test_arteta_agent_routing.py tests/test_arteta_agent_registry.py tests/test_verify_features.py -q`
  - Result: `205 passed, 2 warnings`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed` plus existing Windows asyncio/proactor warnings after completion.
- `python -m pytest tests -q`
  - Result: `489 passed` plus existing Windows asyncio/proactor warnings after completion.

### Remaining

- Provider retry/backoff and capability-based message encoding still need a later focused provider slice.
- `planner.py` still contains substantial routing/response compatibility code and remains a later Phase I thinning target.

### ECS Deployment

- Commit deployed: `9251418 refactor: use fixed provider adapter protocol`.
- Deployment archive: `/tmp/arteta_phase_e_fixed_provider_9251418.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_e_fixed_provider_20260711222000`.
- Remote `py_compile` passed for `planner.py`, provider/routing registry tests, and `tools/verify_features.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Fixed Provider Protocol Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-11 - Phase E Slice: Provider Retry And Backoff

### Scope

- Moved retry/backoff responsibility into the OpenAI-compatible Provider adapter.
- Kept planner/runtime free of provider HTTP retry details.

### Changes

- `OpenAICompatibleProvider` now accepts `max_retries`, `retry_backoff_seconds`, and `retry_status_codes`.
- Default retry policy permits retrying HTTP `408`, `429`, `500`, `502`, `503`, and `504`.
- Transport and timeout failures from `httpx` are retryable.
- Non-retryable HTTP status errors and unclassified programming/data errors are not retried.
- Backoff is exponential and can be disabled in tests with `retry_backoff_seconds=0`.

### Verification

- `python -m pytest tests/test_arteta_agent_provider.py::test_openai_compatible_provider_retries_retryable_status_then_succeeds tests/test_arteta_agent_provider.py::test_openai_compatible_provider_does_not_retry_non_retryable_status -q`
  - RED before fix: failed because `OpenAICompatibleProvider` had no retry configuration.
  - GREEN after fix: `2 passed`.
- `python -m pytest tests/test_arteta_agent_provider.py::test_openai_compatible_provider_does_not_retry_unclassified_errors -q`
  - RED before tightening: failed because unclassified `ValueError` was retried.
  - GREEN after tightening: included in provider suite below.
- `python -m pytest tests/test_arteta_agent_provider.py -q`
  - Result: `10 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `492 passed` plus existing Windows asyncio/proactor warnings printed after completion.

### Remaining

- Capability-based message encoding for providers without standard tool history support remains a later provider slice.

### ECS Deployment

- Commit deployed: `1faaebf refactor: add provider retry policy`.
- Deployment archive: `/tmp/arteta_phase_e_provider_retry_1faaebf.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_e_provider_retry_20260711224000`.
- Remote `py_compile` passed for `plugins/arteta_agent/providers/openai_compatible.py` and `tests/test_arteta_agent_provider.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Provider Retry Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-11 - Phase E Slice: Provider Tool-History Capability Encoding

### Scope

- Made `ProviderCapabilities.supports_tool_history` enforce an actual message encoding branch in the provider adapter.
- Kept Runtime and planner on standard assistant `tool_calls` plus `tool` message history; provider compatibility is handled at the adapter boundary.

### Changes

- Added provider-side `_encode_messages(...)`.
- Providers with `supports_tool_history=True` keep the existing OpenAI-compatible message payload unchanged.
- Providers with `supports_tool_history=False` convert `tool` role messages into `user` data messages labeled `UNTRUSTED_TOOL_RESULT`.
- Synthetic assistant `tool_calls` messages are converted to assistant text summaries containing tool call IDs, tool names, and argument keys only.
- Dynamic tool result content is never moved into `system` during fallback encoding.

### Verification

- `python -m pytest tests/test_arteta_agent_provider.py::test_openai_compatible_provider_encodes_tool_history_for_limited_providers_without_system_leak -q`
  - RED before fix: failed because `role="tool"` was still sent to limited providers.
  - GREEN after fix: `1 passed`.
- `python -m pytest tests/test_arteta_agent_provider.py -q`
  - Result: `11 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `493 passed` plus existing Windows asyncio/proactor warnings printed after completion.

### Remaining

- Planner thinning and broader RouteDecision rollout remain open; Provider Phase E is now closer to the task-book requirements but business-layer legacy HTTP clients still need a separate audit/refactor decision.

### ECS Deployment

- Commit deployed: `9c95086 refactor: encode provider tool history by capability`.
- Deployment archive: `/tmp/arteta_phase_e_provider_capability_9c95086.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_e_provider_capability_20260711225000`.
- Remote `py_compile` passed for `plugins/arteta_agent/providers/openai_compatible.py` and `tests/test_arteta_agent_provider.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Provider Capability Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

### Remaining

- Planner thinning and broader RouteDecision rollout remain open; Provider Phase E is now closer to the task-book requirements but business-layer legacy HTTP clients still need a separate audit/refactor decision.

## 2026-07-11 - Phase F Slice: SQLite Behavior Policy Store

### Scope

- Added a SQLite-backed behavior policy store path while preserving the existing behavior-policy function API.
- Kept JSON storage as fallback when `ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH` is not set, reducing deployment risk for the first slice.
- Implemented one-time legacy JSON import into SQLite when the SQLite database is empty.

### Changes

- `plugins/arteta_agent/behavior_policy.py` now supports `ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH`.
- SQLite tables:
  - `behavior_policies`;
  - `behavior_phrase_styles`.
- SQLite policy writes use `BEGIN IMMEDIATE` transactions.
- TTL semantics:
  - `remaining_turns IS NULL` represents a permanent policy;
  - `consume_group_policy_turn(...)` decrements only finite TTL policies;
  - policies with one remaining turn are removed on consume;
  - permanent route/render/emoji policies are not decremented.
- Legacy JSON migration:
  - imports policies and phrase styles only when SQLite tables are empty;
  - writes a `.bak` copy of the JSON file after successful import;
  - does not re-import once SQLite has data.

### Compatibility

- Existing `set_group_policy`, `get_group_policy`, `list_group_policies`, `delete_group_policy`, `consume_group_policy_turn`, render preference, phrase style, and tool disabled APIs are unchanged.
- Existing tests that set only `ARTETA_AGENT_BEHAVIOR_POLICY_PATH`, `ARTETA_AGENT_UI_PREFS_PATH`, or `ARTETA_AGENT_TOOL_POLICY_PATH` still use JSON fallback.
- SQLite can be enabled independently by setting `ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH`.

### Risk Notes

- This is not yet the final production migration: ECS has not been switched to SQLite by environment variable in this slice.
- Concurrency is improved for SQLite paths through transactions and WAL, but a dedicated concurrent update stress test is still pending.
- Long-term dual write is not implemented; JSON is fallback/import source only.

### Verification

- `python -m pytest tests/test_arteta_agent_behavior_policy_store.py -q`
  - Result: `3 passed`.
- `python -m pytest tests/test_arteta_agent_behavior_policy_store.py tests/test_arteta_agent_registry.py::test_behavior_policy_persists_tool_blocks_and_consumes_ttl tests/test_arteta_agent_registry.py::test_behavior_policy_tools_update_and_show_group_policy tests/test_arteta_agent_registry.py::test_behavior_policy_tools_accept_route_preferences tests/test_arteta_agent_registry.py::test_ui_preferences_are_backed_by_behavior_policy tests/test_arteta_agent_registry.py::test_planner_turns_plain_emoji_ban_into_behavior_policy tests/test_arteta_agent_registry.py::test_agent_loop_uses_behavior_policy_route_for_public_current_questions -q`
  - Result: `9 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `181 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `477 passed` plus existing Windows asyncio/proactor unclosed transport warnings printed after completion.

### Remaining

- Add explicit concurrent update/consume tests.
- Enable SQLite behavior policy path in ECS deployment once migration backup behavior is accepted.
- Remove JSON fallback after a stabilization period, or keep it read-only as an import path only.

### ECS Deployment

- Commit deployed: `6ffd540 refactor: add sqlite behavior policy store`.
- Deployment archive: `/tmp/arteta_phase_f_policy_sqlite_6ffd540.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_f_policy_sqlite_20260711204500`.
- Remote `py_compile` passed for `plugins/arteta_agent/behavior_policy.py` and `tests/test_arteta_agent_behavior_policy_store.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After SQLite Policy Store Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-11 - Phase F Slice: SQLite Behavior Policy Concurrency

### Scope

- Hardened SQLite behavior-policy updates that merge JSON phrase-style rules.
- Added explicit concurrent update and concurrent TTL consume coverage for the SQLite path.

### Changes

- `set_phrase_style(...)` now starts `BEGIN IMMEDIATE` before reading the existing SQLite rule.
- The phrase-style read, JSON merge, and write now happen in one transaction, preventing two writers from both reading the same stale value and overwriting each other's merged fields.
- `consume_group_policy_turn(...)` was already transaction-protected; added a regression test to lock that TTL semantics down.

### Compatibility

- Public behavior-policy APIs are unchanged.
- JSON fallback behavior is unchanged.
- SQLite still remains opt-in via `ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH`.

### Verification

- `python -m pytest tests/test_arteta_agent_behavior_policy_store.py::test_behavior_policy_sqlite_phrase_style_updates_do_not_lose_concurrent_fields -q`
  - RED before fix: failed because one concurrent field was missing from the final phrase style.
  - GREEN after fix: `1 passed`.
- `python -m pytest tests/test_arteta_agent_behavior_policy_store.py -q`
  - Result: `5 passed`.
- `python -m pytest tests/test_arteta_agent_behavior_policy_store.py tests/test_arteta_agent_registry.py::test_behavior_policy_persists_tool_blocks_and_consumes_ttl tests/test_arteta_agent_registry.py::test_behavior_policy_tools_update_and_show_group_policy tests/test_arteta_agent_registry.py::test_behavior_policy_tools_accept_route_preferences tests/test_arteta_agent_registry.py::test_ui_preferences_are_backed_by_behavior_policy tests/test_arteta_agent_registry.py::test_planner_turns_plain_emoji_ban_into_behavior_policy tests/test_arteta_agent_registry.py::test_agent_loop_uses_behavior_policy_route_for_public_current_questions -q`
  - Result: `11 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `181 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `479 passed` plus existing Windows asyncio/proactor warnings printed after completion.

### Remaining

- Enable the SQLite DB path on ECS and verify one-time import/backup behavior with the production supervisor environment.
- Decide whether to keep JSON fallback only as read/import compatibility after the stabilization window.

### ECS Deployment

- Commit deployed: `4fb0c27 fix: harden sqlite behavior policy concurrency`.
- Deployment archive: `/tmp/arteta_phase_f_policy_concurrency_4fb0c27.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_f_policy_concurrency_20260711205500`.
- Remote `py_compile` passed for `plugins/arteta_agent/behavior_policy.py` and `tests/test_arteta_agent_behavior_policy_store.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Policy Concurrency Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-11 - Phase F Slice: Enable SQLite Policy Store On ECS

### Scope

- Updated ECS deployment configuration so the bot and dashboard supervisor processes opt into the SQLite behavior-policy store.
- Verified the live ECS migration path from the legacy JSON file into `/opt/arteta_bot/data/agent_behavior_policy.db`.

### Changes

- `deploy/deploy_ecs.sh` now sets `ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH=/opt/arteta_bot/data/agent_behavior_policy.db` for both `arteta_bot` and `arteta_dashboard`.
- Added deployment-script coverage to prevent future ECS installs from silently falling back to JSON policy storage.

### ECS Migration Verification

- Remote supervisor config backup: `/opt/arteta_bot/backups/supervisor_policy_sqlite_20260711210500`.
- Existing legacy file before migration: `/opt/arteta_bot/config/agent_behavior_policy.json`.
- Migration trigger created `/opt/arteta_bot/data/agent_behavior_policy.db`.
- SQLite verification:
  - `behavior_policies`: 2 rows.
  - `behavior_phrase_styles`: 0 rows.
- Legacy backup created: `/opt/arteta_bot/config/agent_behavior_policy.json.bak`.
- Corrected ownership for the SQLite DB and backup file to `arteta:arteta`.

### Verification

- `python -m pytest tests/dashboard/test_deploy_ecs_dashboard.py::test_ecs_deploy_script_enables_sqlite_behavior_policy_store -q`
  - RED before fix: failed because the deploy script did not set `ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH`.
- `python -m pytest tests/dashboard/test_deploy_ecs_dashboard.py -q`
  - Result: `4 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `181 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `480 passed` plus existing Windows asyncio/proactor warnings printed after completion.

### ECS Smoke After SQLite Policy Enablement

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

### Remaining

- Keep JSON support as an import/fallback path for now; do not dual-write.
- Later cleanup can make the fallback read-only after more production soak time.

## 2026-07-11 - Phase G Slice: Explicit Confirmation Failure Audit

### Scope

- Closed an audit gap for explicit PendingAction confirmation attempts that fail before reaching the executor.
- Added direct timeout audit coverage for tool execution.

### Changes

- `plugins/arteta_agent/audit.py` now exposes `record_pending_confirmation_failure(...)` for sanitized confirmation rejection records.
- `planner._execute_explicit_pending_action_confirmation(...)` records an audit event when an action ID is missing, expired, already consumed, or otherwise unavailable.
- The new audit detail stores only structured metadata: event, request_id, confirmed_action_id, arg_keys, and duration_ms.

### Verification

- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_audits_explicit_missing_pending_confirmation -q`
  - RED before fix: failed with zero audit records.
  - GREEN after fix: `1 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_executor_audits_invalid_arguments_without_raw_values tests/test_arteta_agent_registry.py::test_executor_audits_pending_action_creation_without_raw_values tests/test_arteta_agent_registry.py::test_executor_audits_confirmed_action_success_without_raw_values tests/test_arteta_agent_registry.py::test_executor_audits_failed_confirmation_without_raw_values tests/test_arteta_agent_registry.py::test_agent_loop_audits_explicit_missing_pending_confirmation tests/test_arteta_agent_registry.py::test_executor_audits_tool_error_code_without_raw_error_text tests/test_arteta_agent_registry.py::test_executor_audits_tool_timeout_without_raw_values -q`
  - Result: `7 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `183 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `482 passed` plus existing Windows asyncio/proactor warnings printed after completion.

### Remaining

- Review whether successful admin handlers that also write their own audit logs should be normalized to executor-only events in a later cleanup.
- Continue checking persistent audit coverage for duplicate consumed confirmations through the explicit planner path.

### ECS Deployment

- Commit deployed: `2f7623d feat: audit explicit confirmation failures`.
- Deployment archive: `/tmp/arteta_phase_g_audit_confirm_2f7623d.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_g_audit_confirm_20260711212000`.
- Remote `py_compile` passed for `plugins/arteta_agent/audit.py`, `plugins/arteta_agent/planner.py`, and `tests/test_arteta_agent_registry.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Confirmation Audit Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-11 - Phase G Slice: Admin Permission Denial Audit Coverage

### Scope

- Added explicit regression coverage for persistent audit records when a non-admin user requests an `admin_action` tool.

### Changes

- Added `test_executor_audits_admin_permission_denial_without_raw_values`.
- Confirmed the existing executor `permission_denied` audit path stores only structured metadata and does not create a PendingAction for non-admin users.

### Verification

- `python -m pytest tests/test_arteta_agent_registry.py::test_executor_audits_admin_permission_denial_without_raw_values -q`
  - Result: `1 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_executor_audits_invalid_arguments_without_raw_values tests/test_arteta_agent_registry.py::test_executor_audits_pending_action_creation_without_raw_values tests/test_arteta_agent_registry.py::test_executor_audits_admin_permission_denial_without_raw_values tests/test_arteta_agent_registry.py::test_executor_audits_confirmed_action_success_without_raw_values tests/test_arteta_agent_registry.py::test_executor_audits_failed_confirmation_without_raw_values tests/test_arteta_agent_registry.py::test_agent_loop_audits_explicit_missing_pending_confirmation tests/test_arteta_agent_registry.py::test_executor_audits_tool_error_code_without_raw_error_text tests/test_arteta_agent_registry.py::test_executor_audits_tool_timeout_without_raw_values -q`
  - Result: `8 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `483 passed` plus existing Windows asyncio/proactor warnings printed after completion.

### ECS Deployment

- Commit deployed: `9d7c8c7 test: cover admin permission audit`.
- Deployment archive: `/tmp/arteta_phase_g_admin_audit_test_9d7c8c7.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_g_admin_audit_test_20260711212800`.
- Remote `py_compile` passed for `tests/test_arteta_agent_registry.py`.
- `arteta_bot` and `arteta_dashboard` remained `RUNNING`; no restart was needed because this slice only changed tests/devlog.

### ECS Smoke After Admin Audit Coverage Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-11 - Phase H Slice: Parallel-Safe Read Runtime

### Scope

- Enabled bounded concurrent execution for independent read-only tool calls inside the unified Runtime.

### Changes

- `AgentRunConfig` now includes `max_parallel_tools` with default `3`.
- `AgentRuntimeRunner` groups only contiguous tool calls whose `ToolSpec` is:
  - `permission == "safe_read"`;
  - `parallel_safe == True`;
  - `idempotent == True`.
- Mixed read/write/admin calls remain serial.
- Result observation, trace order, tool result order, tool-call ID mapping, LoopGuard checks, permission stopping, observer hooks, and observation budget checks still run in original call order.

### Verification

- `python -m pytest tests/test_arteta_agent_runtime.py::test_runtime_runner_executes_parallel_safe_read_tools_concurrently_in_order -q`
  - RED before fix: failed because `AgentRunConfig` had no `max_parallel_tools`.
  - GREEN after fix: `1 passed`.
- `python -m pytest tests/test_arteta_agent_runtime.py -q`
  - Result: `9 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_runtime.py tests/test_arteta_agent_registry.py -q`
  - Result: `193 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `487 passed, 2 warnings`.

### Remaining

- Add a planner-level multi-read test if later routing/planning work emits multiple independent safe-read calls in one model turn.

### ECS Deployment

- Commit deployed: `a71b958 feat: run parallel-safe read tools concurrently`.
- Deployment archive: `/tmp/arteta_phase_h_parallel_reads_a71b958.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_h_parallel_reads_20260711214000`.
- Remote `py_compile` passed for `plugins/arteta_agent/runtime/config.py`, `plugins/arteta_agent/runtime/runner.py`, and `tests/test_arteta_agent_runtime.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Parallel Runtime Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase C Slice: Memory Preference Plan Route

### Scope

- Migrated the explicit `remember_user_preference` forced branch out of `planner.py` and into the structured Routing + Planning path.
- Kept the existing user-facing behavior for explicit future preferences:
  - single memory-preference requests still execute `remember_user_preference` immediately and return the tool response;
  - multi-intent requests such as memory preference plus PDF analysis still execute both required tools and then continue through the unified Runtime for model composition.

### Changes

- Added `detect_memory_preference_args(...)` to `routing/contextual_tools.py`, preserving the prior preference-shape logic for:
  - explicit `记住` requests;
  - `以后/下次` plus preference-shape requests such as "我说...", "提醒我...", reply style, names, colors, and replacements.
- `heuristic_router.route_message(...)` now emits the `memory_preference` intent from that detector instead of the previous broad marker check.
- `build_plan(...)` now marks a single `remember_user_preference` required tool as `execute_single_required_tool` and `direct_tool_response`.
- Removed `detect_forced_memory_args(...)` and the `forced-remember-user-preference` branch from `planner.py`.

### Compatibility and Safety

- No tool names, schemas, permissions, or handler behavior changed.
- The memory tool still runs through the same planned initial-tool Runtime path used by trace, UI preference, and other structured required tools.
- The broad phrase "下次阿森纳比赛几点" no longer becomes a memory write just because it contains `下次`.
- UI preference requests keep taking the controlled `update_ui_preference` route and are not silently written into long-term memory.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py::test_contextual_tools_detects_memory_preference_args_for_future_rules tests/test_arteta_agent_routing.py::test_plan_builder_routes_memory_preference_requests_as_direct_required_tool tests/test_arteta_agent_routing.py::test_planner_no_longer_has_forced_memory_preference_branch -q`
  - RED before fix: failed because the routing detector did not exist, the plan lacked direct-tool constraints, and planner still had the forced memory branch.
  - GREEN after fix: `3 passed`.
- `python -m pytest tests/test_arteta_agent_routing.py::test_contextual_tools_detects_memory_preference_args_for_future_rules tests/test_arteta_agent_routing.py::test_plan_builder_routes_memory_preference_requests_as_direct_required_tool tests/test_arteta_agent_routing.py::test_planner_no_longer_has_forced_memory_preference_branch tests/test_arteta_agent_routing.py::test_plan_builder_combines_memory_preference_and_document_context tests/test_arteta_agent_routing.py::test_agent_loop_executes_multi_intent_memory_and_document_plan tests/test_arteta_agent_registry.py::test_agent_loop_forces_memory_tool_for_explicit_future_preference tests/test_arteta_agent_registry.py::test_agent_loop_forces_memory_tool_for_reply_phrase_style_preference -q`
  - Result: `7 passed`.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `18 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `510 passed, 2 warnings`.

### Remaining

- `planner.py` still contains legacy forced branches for document/link/web/science flows; migrate them one slice at a time after adding equivalent plan tests.
- Continue reducing planner constants and helper logic only when a structured routing/planning/response owner exists.

### ECS Deployment

- Commit deployed: `5f56620 refactor: route memory preferences through agent plan`.
- Deployment archive: `/tmp/arteta_phase_c_memory_plan_5f56620.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_memory_plan_20260712014408`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/planning/plan_builder.py`;
  - `plugins/arteta_agent/routing/contextual_tools.py`;
  - `plugins/arteta_agent/routing/heuristic_router.py`;
  - `tests/test_arteta_agent_routing.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Memory Preference Plan Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase C Slice: Link Analysis Plan Route

### Scope

- Migrated the detected-link `analyze_links` forced branch out of `planner.py` and into the structured Routing + Planning path.
- Preserved existing behavior: link analysis is executed before the model response, and the tool observation is then summarized by the model instead of being returned directly.

### Changes

- Moved the link-analysis intent markers into `routing/heuristic_router.py`.
- `route_message(...)` now emits a `link_analysis` intent and required `analyze_links` call when `ctx.extra.detected_urls` is present and the user asks to analyze/summarize/view the link.
- `build_plan(...)` marks a single `analyze_links` required tool as `execute_single_required_tool` without `direct_tool_response`.
- Removed `LINK_INTENT_MARKERS`, `should_force_link_analysis_tool(...)`, and the `forced-analyze-links` branch from `planner.py`.

### Compatibility and Safety

- No tool schema, permission, or handler behavior changed.
- Unrelated messages that merely carry a detected URL do not force `analyze_links`.
- Plain link intent still prefers `analyze_links` over `read_document` when both tools exist.
- Link snapshot artifact compatibility remains covered through the existing response composer path.

### Verification

- Initial RED used the same route/removal assertions under the temporary name `test_plan_builder_routes_link_analysis_requests_as_direct_required_tool`; it failed because the router did not emit `link_analysis` and planner still had the forced link branch.
  - During implementation review, the assertion was corrected to match legacy behavior: `analyze_links` should not set `direct_tool_response` because the model still summarizes the tool observation.
- `python -m pytest tests/test_arteta_agent_routing.py::test_plan_builder_routes_link_analysis_requests_as_required_tool tests/test_arteta_agent_routing.py::test_routing_does_not_force_link_analysis_without_link_intent tests/test_arteta_agent_routing.py::test_planner_no_longer_has_forced_link_analysis_branch tests/test_arteta_agent_registry.py::test_agent_loop_forces_link_analysis_when_link_is_present tests/test_arteta_agent_registry.py::test_agent_loop_prefers_link_analysis_for_plain_link_intent_when_document_tool_exists tests/test_arteta_agent_registry.py::test_agent_loop_preserves_link_snapshot_artifact_after_model_summary -q`
  - GREEN after fix: `6 passed`.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `21 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `513 passed, 2 warnings`.

### Remaining

- `planner.py` still contains legacy forced branches for document, web verification, and science tools.
- The document branch should be migrated separately because it has two argument modes: current-message document attachments and detected document URLs.

### ECS Deployment

- Commit deployed: `c78922a refactor: route link analysis through agent plan`.
- Deployment archive: `/tmp/arteta_phase_c_link_plan_c78922a.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_link_plan_20260712015327`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/planning/plan_builder.py`;
  - `plugins/arteta_agent/routing/heuristic_router.py`;
  - `tests/test_arteta_agent_routing.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Link Analysis Plan Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase C Slice: Document Read Plan Route

### Scope

- Migrated the deterministic `read_document` forced branch out of `planner.py` and into the structured Routing + Planning path.
- Preserved both legacy document argument modes:
  - current-message document attachments call `read_document` with `{}`;
  - detected document/download URLs call `read_document` with `{"url": first_detected_url}`.

### Changes

- Moved document intent markers into `routing/heuristic_router.py`.
- Added `_document_tool_args(...)` in the router to produce structured `read_document` arguments from `ctx.extra.document_urls` or `ctx.extra.detected_urls`.
- `route_message(...)` now keeps processing structured document/link context even when the latest user text is empty.
- Document routing now takes precedence over link analysis for detected URL turns with explicit PDF/document intent.
- `build_plan(...)` marks a single `read_document` required tool as `execute_single_required_tool` without `direct_tool_response`.
- Removed `DOCUMENT_INTENT_MARKERS`, `DETECTED_URL_DOCUMENT_INTENT_MARKERS`, `should_force_document_tool(...)`, `forced_document_tool_args(...)`, and the `forced-read-document` branch from `planner.py`.

### Compatibility and Safety

- No tool schema, permission, or handler behavior changed.
- Document tool observations still enter the unified Runtime as tool messages, then the model summarizes them.
- The prompt-injection regression for document/tool text staying out of system messages still passes.
- Plain link intent still routes to `analyze_links`, not `read_document`.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py::test_plan_builder_routes_document_attachment_as_required_tool_for_empty_text tests/test_arteta_agent_routing.py::test_plan_builder_routes_detected_document_url_with_url_argument tests/test_arteta_agent_routing.py::test_routing_prefers_link_analysis_over_document_for_plain_link_intent tests/test_arteta_agent_routing.py::test_planner_no_longer_has_forced_document_branch -q`
  - RED before fix: failed because empty text with document context returned no route, detected PDF URL routed to `analyze_links`, and planner still had the forced document branch.
- `python -m pytest tests/test_arteta_agent_routing.py::test_plan_builder_routes_document_attachment_as_required_tool_for_empty_text tests/test_arteta_agent_routing.py::test_plan_builder_routes_detected_document_url_with_url_argument tests/test_arteta_agent_routing.py::test_routing_prefers_link_analysis_over_document_for_plain_link_intent tests/test_arteta_agent_routing.py::test_planner_no_longer_has_forced_document_branch tests/test_arteta_agent_registry.py::test_agent_loop_forces_document_tool_when_document_is_present tests/test_arteta_agent_registry.py::test_agent_loop_keeps_forced_tool_result_out_of_system_messages tests/test_arteta_agent_registry.py::test_agent_loop_continues_when_forced_tool_followup_requests_another_tool tests/test_arteta_agent_registry.py::test_agent_loop_forces_document_tool_for_pdf_intent_with_plain_download_url tests/test_arteta_agent_registry.py::test_agent_loop_prefers_link_analysis_for_plain_link_intent_when_document_tool_exists -q`
  - GREEN after fix: `9 passed`.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `25 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `517 passed, 2 warnings`.

### Remaining

- `planner.py` still contains legacy forced branches for public web verification and science tools.
- Science tools intentionally return direct user-facing text today; migrate only after adding tests that preserve that direct-response behavior.

### ECS Deployment

- Commit deployed: `25cf29e refactor: route document reads through agent plan`.
- Deployment archive: `/tmp/arteta_phase_c_document_plan_25cf29e.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_document_plan_20260712020247`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/planning/plan_builder.py`;
  - `plugins/arteta_agent/routing/heuristic_router.py`;
  - `tests/test_arteta_agent_routing.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Document Read Plan Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase C Slice: Public Current Fact Plan Route

### Scope

- Migrated the public-current-fact web verification forced branch out of `planner.py` and into the structured Routing + Planning path.
- Preserved route policy behavior for preferred tools and registry-aware fallback.
- Kept current fact + local memory multi-intent behavior, while preventing pure memory recall from being forced into web verification.

### Changes

- `routing/heuristic_router.py` now detects recent public match questions such as "西班牙和比利时最近的一场比赛" and emits a `public_current_fact` intent with required `grok_search`.
- The router now preserves the previous query enrichment for Chinese Arsenal transfer questions:
  - add `Arsenal` when the text contains `阿森纳`;
  - add `transfer news` when the text contains `转会`.
- Added a local-memory guard: turns with memory markers such as `昨天/之前/还记得` only add web verification when they also include explicit current verification intent such as `现在查/查最新/最新/新闻/来源/核实/结果/转会/伤病`.
- `build_plan(...)` now accepts `disabled_tools` and `is_tool_available` so public-current-fact rewrite can select the configured preferred tool and still fall back when that tool is unavailable.
- `planner.run_agent_loop(...)` passes disabled tools and registry availability into `build_plan(...)`.
- Removed `detect_forced_web_verification_args(...)` and the forced web verification execution branch from `planner.py`.

### Debugging Note

- Initial migration caused `tools\\verify_features.py --suite agent_loop` to fail `lets_llm_choose_memory_for_yesterday_prediction_score`.
- Root cause: the router interpreted "昨天预测的这场比赛的比分" as both local memory and current fact because `比分/比赛` matched public fact markers.
- Fix: keep local memory and current fact composable, but require an explicit current-verification marker before adding web verification to local-memory turns.

### Compatibility and Safety

- No tool schemas, names, permissions, or handlers changed.
- Route policy still supports `route.public_current_fact.preferred_tool`.
- If the preferred public-current-fact tool is unavailable, planner-time plan construction falls back to an available web verifier/search tool.
- Unavailable web verification results still remain out of system messages and enter the Runtime as tool/user context.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py::test_plan_builder_routes_recent_team_match_questions_to_grok_search tests/test_arteta_agent_routing.py::test_planner_no_longer_has_forced_web_verification_branch tests/test_arteta_agent_registry.py::test_agent_loop_does_not_force_web_for_group_local_recent_context tests/test_arteta_agent_registry.py::test_agent_loop_does_not_force_web_for_casual_future_or_current_words -q`
  - RED before fix: failed because planner still defined the forced web detector/branch.
- `python -m pytest tests/test_arteta_agent_routing.py::test_plan_builder_keeps_memory_score_recall_out_of_forced_web -q`
  - RED before guard fix: failed because the plan included both `query_group_memory` and a web verification tool for a pure memory recall.
- `python -m pytest tests/test_arteta_agent_routing.py::test_plan_builder_keeps_memory_score_recall_out_of_forced_web tests/test_arteta_agent_routing.py::test_plan_builder_combines_group_memory_and_latest_web_verification tests/test_arteta_agent_routing.py::test_plan_builder_routes_recent_team_match_questions_to_grok_search tests/test_arteta_agent_routing.py::test_planner_no_longer_has_forced_web_verification_branch tests/test_arteta_agent_registry.py::test_agent_loop_falls_back_to_grok_when_route_policy_tool_is_unavailable tests/test_arteta_agent_registry.py::test_agent_loop_continues_answering_when_forced_web_verification_is_unavailable tests/test_arteta_agent_registry.py::test_agent_loop_lets_llm_choose_memory_for_yesterday_prediction_score -q`
  - GREEN after fix: `7 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `28 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `520 passed, 2 warnings`.

### Remaining

- `planner.py` still contains the direct science-tool forced branch.
- Continue reducing planner-owned marker constants after science routing and contextual exposure are separated cleanly.

### ECS Deployment

- Commit deployed: `cafa288 refactor: route public current facts through agent plan`.
- Deployment archive: `/tmp/arteta_phase_c_public_fact_plan_cafa288.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_public_fact_plan_20260712021555`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/planning/plan_builder.py`;
  - `plugins/arteta_agent/routing/heuristic_router.py`;
  - `tests/test_arteta_agent_registry.py`;
  - `tests/test_arteta_agent_routing.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Public Current Fact Plan Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase C Slice: Direct Technical Tool Plan Route

### Scope

- Migrated the direct-response science/math/code/algorithm forced branch out of `planner.py` and into the structured Routing + Planning path.
- Preserved the legacy direct-response behavior: technical solver tools return their tool result directly and do not require a follow-up model summary.

### Changes

- `routing/heuristic_router.py` now maps explicit technical solve requests to:
  - `solve_algorithm_problem`;
  - `solve_code_question`;
  - `solve_science_question`;
  - `solve_math_question`.
- `build_plan(...)` now marks single direct technical tools as both `execute_single_required_tool` and `direct_tool_response`.
- Removed the `forced_science_tool` execution branch from `planner.py`.
- Kept planner's science marker/helper code for contextual tool exposure for now; that will be moved separately because it controls tool schema visibility, not forced execution.

### Compatibility and Safety

- No tool schema, permission, or handler behavior changed.
- Obvious math questions still execute `solve_math_question` and return the tool result directly.
- Scoreline-like chat still hides `solve_math_question` from model exposure and does not force a math tool.
- The Runtime remains the single path for the planned direct technical tool execution.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py::test_plan_builder_routes_math_questions_as_direct_required_tool tests/test_arteta_agent_routing.py::test_planner_no_longer_has_forced_science_branch -q`
  - RED before fix: failed because the math plan lacked direct-tool constraints and planner still contained the forced science branch.
- `python -m pytest tests/test_arteta_agent_routing.py::test_plan_builder_routes_math_questions_as_direct_required_tool tests/test_arteta_agent_routing.py::test_planner_no_longer_has_forced_science_branch tests/test_arteta_agent_registry.py::test_agent_loop_forces_math_tool_for_obvious_math_question tests/test_arteta_agent_registry.py::test_agent_loop_does_not_expose_math_tool_for_scoreline_chat -q`
  - GREEN after fix: `4 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `30 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `522 passed, 2 warnings`.

### Remaining

- `planner.py` still has forced helper functions for behavior/tool policy updates and mood emoji post-processing.
- `_answer_from_forced_tool_result(...)` may now be dead after document/link/web migration; verify before removal.
- Move contextual exposure marker logic out of planner in a separate low-risk slice.

### ECS Deployment

- Commit deployed: `258cb18 refactor: route technical solvers through agent plan`.
- Deployment archive: `/tmp/arteta_phase_c_technical_plan_258cb18.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_technical_plan_20260712022650`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/planning/plan_builder.py`;
  - `plugins/arteta_agent/routing/heuristic_router.py`;
  - `tests/test_arteta_agent_routing.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Technical Solver Plan Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase C Cleanup: Remove Legacy Forced Tool Followup Helper

### Scope

- Removed the unused `_answer_from_forced_tool_result(...)` helper after document, link, public-current-fact, and technical forced routes had all moved into structured plan execution.
- Removed its private support helpers:
  - `_forced_tool_followup_instruction(...)`;
  - `_forced_tool_call_history_message(...)`;
  - `_forced_followup_disabled_tools(...)`.
- Kept `_run_forced_tool_direct(...)` unchanged because behavior-policy and tool-policy instructions still use that direct structured Runtime path.

### Compatibility and Safety

- No tool names, schemas, permissions, provider behavior, or handler behavior changed.
- Existing forced initial tool calls still execute through `_run_runtime_loop_from_state(...)`.
- The prompt-injection safety behavior is now covered by Runtime tests that assert untrusted tool output appears in `tool` messages and not in dynamic `system` messages.
- This cleanup removes a stale static system helper instead of replacing it with another system-message path.

### Verification

- `python -m pytest tests/test_arteta_agent_registry.py::test_planner_no_longer_defines_legacy_forced_tool_followup_helpers -q`
  - RED before cleanup: failed because `_answer_from_forced_tool_result(...)` was still defined.
- `python -m pytest tests/test_arteta_agent_registry.py::test_planner_no_longer_defines_legacy_forced_tool_followup_helpers tests/test_arteta_agent_registry.py::test_agent_loop_keeps_forced_tool_result_out_of_system_messages tests/test_arteta_agent_registry.py::test_agent_loop_continues_when_forced_tool_followup_requests_another_tool -q`
  - GREEN after cleanup: `3 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `30 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `522 passed, 2 warnings`.

### Remaining

- `planner.py` still owns contextual tool exposure marker logic.
- Behavior/tool-policy direct update branches still use `_run_forced_tool_direct(...)` and need to be planned separately before removal.
- Existing Windows asyncio/proactor resource warnings remain unrelated to this cleanup.

### ECS Deployment

- Commit deployed: `0e91414 refactor: remove legacy forced tool followup helper`.
- Deployment archive: `/tmp/arteta_phase_c_forced_followup_cleanup_0e91414.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_forced_followup_cleanup_20260712023413`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `tests/test_arteta_agent_registry.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Forced Followup Cleanup Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase C Slice: Extract Contextual Tool Exposure Rules

### Scope

- Moved contextual tool schema exposure and exclusion rules from `planner.py` into `routing/contextual_tools.py`.
- Kept the existing planner behavior: planner still computes `schema_excluded_tools`, but it now delegates category/marker decisions to routing.
- Preserved existing UI preference and memory preference detectors in `routing/contextual_tools.py`.

### Changes

- `planner.py` no longer defines:
  - `detect_contextual_tool_exclusions(...)`;
  - science/math exposure helpers;
  - football, group, web, document, image, render, policy, action, admin marker constants for schema exposure.
- `routing/contextual_tools.py` now owns:
  - contextual category marker constants;
  - scoreline-vs-math exposure guard;
  - `detect_contextual_tool_exclusions(...)`.
- Added a structure regression test to keep contextual exposure rules out of planner.

### Compatibility and Safety

- No route plan, tool schema, permission, handler, or Runtime execution behavior changed.
- Ordinary chat still hides unrelated tools.
- Football intents still keep football and web tools visible.
- Scoreline-like chat still hides `solve_math_question`.
- Document/link required-tool turns still hide the already executed tool from follow-up model calls.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py::test_planner_no_longer_owns_contextual_tool_exposure_rules -q`
  - RED before extraction: failed because planner still defined `detect_contextual_tool_exclusions(...)`.
- `python -m py_compile plugins\\arteta_agent\\planner.py plugins\\arteta_agent\\routing\\contextual_tools.py`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_routing.py::test_planner_no_longer_owns_contextual_tool_exposure_rules tests/test_arteta_agent_registry.py::test_agent_loop_keeps_football_tools_for_football_intent tests/test_arteta_agent_registry.py::test_agent_loop_forces_document_tool_for_pdf_intent_with_plain_download_url tests/test_arteta_agent_registry.py::test_agent_loop_forces_link_analysis_when_link_is_present tests/test_arteta_agent_registry.py::test_agent_loop_does_not_expose_math_tool_for_scoreline_chat -q`
  - Result: `5 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `31 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `523 passed, 2 warnings`.

### Remaining

- `planner.py` still owns behavior/tool-policy direct update branches.
- `_answer_after_unavailable_web_result(...)` remains as a compatibility helper and should be revisited separately.
- Existing Windows asyncio/proactor resource warnings remain unrelated to this extraction.

### ECS Deployment

- Commit deployed: `29ac74c refactor: extract contextual tool exposure rules`.
- Deployment archive: `/tmp/arteta_phase_c_contextual_exposure_29ac74c.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_contextual_exposure_20260712025046`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/routing/contextual_tools.py`;
  - `tests/test_arteta_agent_routing.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Contextual Exposure Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase C Cleanup: Remove Unreachable Inline Runtime Loop

### Scope

- Removed unreachable legacy loop code from `_run_loop_from_state(...)` after its Runtime delegation return.
- Removed private planner helpers that only served that unreachable loop:
  - `_state_has_tool_call(...)`;
  - `_trace_has_tool(...)`;
  - `_trace_has_any_tool(...)`;
  - `_should_allow_forced_mood_emoji(...)`;
  - `detect_forced_mood_emoji_args(...)`;
  - `_tool_call_signature(...)`.

### Compatibility and Safety

- Runtime behavior is unchanged because `_run_loop_from_state(...)` already returned from `_run_runtime_loop_from_state(...)` before reaching the deleted code.
- Mood emoji behavior remains owned by `response/mood.py` and invoked through `_runtime_finalizer(...)`.
- Loop guard signature, permission-required stop, observation budget, and finalizer handling remain in Runtime.

### Verification

- `python -m pytest tests/test_arteta_agent_mood_response.py::test_planner_no_longer_keeps_unreachable_inline_mood_loop -q`
  - RED before cleanup: failed because planner still defined the mood wrapper and unreachable loop text.
- `python -m py_compile plugins\\arteta_agent\\planner.py`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_mood_response.py::test_planner_no_longer_keeps_unreachable_inline_mood_loop tests/test_arteta_agent_mood_response.py::test_mood_finalizer_sends_negative_emoji_when_reply_skips_tool tests/test_arteta_agent_mood_response.py::test_mood_finalizer_respects_disabled_or_existing_emoji_call -q`
  - Result: `3 passed`.
- `python -m pytest tests/test_arteta_agent_mood_response.py -q`
  - Result: `4 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `184 passed, 2 warnings`.
- `python -m pytest tests -q`
  - Result: `523 passed, 2 warnings`.

### Remaining

- `planner.py` still owns behavior/tool-policy direct update branches.
- `_answer_after_unavailable_web_result(...)` remains as a compatibility helper and should be revisited separately.
- Existing Windows asyncio/proactor resource warnings remain unrelated to this cleanup.

### ECS Deployment

- Commit deployed: `8630e6f refactor: remove unreachable planner runtime loop`.
- Deployment archive: `/tmp/arteta_phase_c_unreachable_runtime_loop_8630e6f.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_unreachable_runtime_loop_20260712025900`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `tests/test_arteta_agent_mood_response.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Unreachable Runtime Loop Cleanup Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase C Cleanup: Remove Unavailable Web Fallback Helper

### Scope

- Removed unused `_answer_after_unavailable_web_result(...)` from `planner.py`.
- Removed unused `_web_verification_unavailable(...)` from `planner.py`.
- Replaced the direct helper regression with a structure regression proving the planner no longer defines the unavailable-web fallback helper or its dynamic-data marker.

### Compatibility and Safety

- Production unavailable-web handling continues through the unified Runtime tool observation path.
- There is no longer a special fallback helper that can construct a follow-up `system` message around failed web verification results.
- Dynamic web/tool result content remains outside `system` messages in this path; unavailable web observations are handled as tool observations and final Runtime responses.
- Existing X post unavailable degradation remains covered by `fetch_x_post` behavior and trace/runtime tests.

### Verification

- `python -m pytest tests/test_arteta_agent_registry.py::test_planner_no_longer_defines_unavailable_web_fallback_helper -q`
  - RED before cleanup: failed because planner still defined the helper.
- `python -m py_compile plugins\\arteta_agent\\planner.py tests\\test_arteta_agent_registry.py`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py::test_planner_no_longer_defines_unavailable_web_fallback_helper tests/test_arteta_agent_registry.py::test_agent_loop_continues_answering_when_forced_web_verification_is_unavailable tests/test_arteta_agent_registry.py::test_trace_marks_x_post_unavailable_as_unavailable -q`
  - Result: `3 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `31 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `183 passed, 3 warnings`.
- `python -m pytest tests -q`
  - Result: `522 passed, 2 warnings`.

### Remaining

- `planner.py` still owns behavior/tool-policy direct update branches that call `_run_forced_tool_direct(...)`.
- `planner.py` still exposes provider compatibility entry points and provider call wrappers for legacy tests and callers.
- Existing Windows asyncio/proactor resource warnings remain unrelated to this cleanup.

### ECS Deployment

- Commit deployed: `5253014 refactor: remove unavailable web fallback helper`.
- Deployment archive: `/tmp/arteta_phase_c_unavailable_web_cleanup_5253014.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_unavailable_web_cleanup_20260712031051`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `tests/test_arteta_agent_registry.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Unavailable Web Cleanup Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase C Cleanup: Route Behavior Policy Updates Through Plans

### Scope

- Moved explicit behavior-policy update detection from `planner.py` into `routing/heuristic_router.py`.
- Moved temporary tool-block commands into routing as `tool_policy_update` intents backed by the existing `update_behavior_policy` tool.
- Removed `_run_forced_tool_direct(...)` from `planner.py`.
- Removed the planner-level direct branches for:
  - `behavior_policy.parse_behavior_policy_instruction(...)`;
  - `parse_tool_block_instruction(...)`;
  - direct fallback `behavior_policy.set_group_policy(...)`;
  - direct fallback `set_group_tool_block(...)`.

### Design Decision

- Behavior preference parsing is routing context, not Runtime behavior.
- The actual state change still happens through the registered `update_behavior_policy` tool, so server-side schema validation, permissions, trace, Runtime limits, and ToolResult handling remain on the same path as other required tools.
- Production behavior remains compatible because the normal phase-3 tool registration includes `update_behavior_policy`.
- Tests that previously relied on a registry missing `update_behavior_policy` were adjusted to register the real behavior policy tool, matching the production registry path.

### Compatibility and Safety

- User-facing behavior for plain emoji bans is preserved: the policy is written, and the following handled turn consumes one TTL.
- Temporary tool blocks still persist as `tool.<name>.disabled=true` policies and hide the tool from later model schema exposure.
- The planner no longer creates a parallel direct execution path for policy writes.
- Policy writes continue to use existing Behavior Policy validation, including key prefix validation and forbidden key parts.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py::test_plan_builder_routes_behavior_policy_instruction_as_required_tool tests/test_arteta_agent_routing.py::test_plan_builder_routes_tool_block_instruction_as_behavior_policy_tool tests/test_arteta_agent_routing.py::test_planner_no_longer_has_direct_behavior_or_tool_policy_update_branches -q`
  - RED before implementation: failed because routing did not emit policy-update intents and planner still had direct branches.
  - Result after implementation: `3 passed`.
- `python -m py_compile plugins\\arteta_agent\\planner.py plugins\\arteta_agent\\routing\\heuristic_router.py tests\\test_arteta_agent_routing.py tests\\test_arteta_agent_registry.py`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `34 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `183 passed, 3 warnings`.
- `python -m pytest tests/test_arteta_agent_behavior_policy_store.py tests/test_arteta_agent_runtime.py -q`
  - Result: `14 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `525 passed`.

### Remaining

- `planner.py` still exposes provider compatibility entry points and provider call wrappers for legacy tests and callers.
- `planner.py` still performs compatibility orchestration around route, plan, Runtime, response composition, and pending confirmations.
- Existing Windows asyncio/proactor resource warnings remain unrelated to this cleanup.

### ECS Deployment

- Commit deployed: `adc3fa5 refactor: route policy updates through agent plan`.
- Deployment archive: `/tmp/arteta_phase_c_policy_plan_adc3fa5.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_policy_plan_20260712032335`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/routing/heuristic_router.py`;
  - `tests/test_arteta_agent_routing.py`;
  - `tests/test_arteta_agent_registry.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Policy Plan Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase E Cleanup: Move Provider Chat Wrapper Out Of Planner

### Scope

- Added `plugins/arteta_agent/providers/chat_completion.py`.
- Moved the concrete provider chat-completion wrapper out of `planner.py`.
- Kept `planner.call_llm_with_tools(...)` as a compatibility wrapper for existing callers and tests.
- `planner.py` no longer directly imports or constructs:
  - `OpenAICompatibleProvider`;
  - `get_shared_async_client`;
  - `build_openai_tools`.

### Design Decision

- Provider-layer code now owns tool schema construction for model requests, shared client access, provider adapter construction, and request timeout/temperature forwarding.
- Planner keeps only the legacy function name so Runtime tests and monkeypatch-based callers can continue to replace `planner.call_llm_with_tools(...)`.
- The provider wrapper uses the existing shared HTTP client and OpenAI-compatible adapter, so retry, response parsing, reasoning content, and capability behavior stay centralized.

### Compatibility and Safety

- `run_agent_loop(...)` signature and behavior are unchanged.
- `planner.ProviderResponseError` and `_parse_chat_response(...)` compatibility remain available.
- Provider payload behavior remains unchanged:
  - visible tools are still built from the registry;
  - hidden/disabled tools remain excluded;
  - no `tools` field is sent when no tools are visible;
  - timeout and temperature are still forwarded.

### Verification

- `python -m pytest tests/test_arteta_agent_provider.py::test_provider_chat_completion_wrapper_builds_tool_schema_and_reuses_client tests/test_arteta_agent_provider.py::test_planner_provider_entrypoint_is_compatibility_wrapper_only -q`
  - RED before implementation: failed because `providers.chat_completion` did not exist and planner still imported provider/client/schema helpers.
  - Result after implementation: `2 passed`.
- `python -m py_compile plugins\\arteta_agent\\planner.py plugins\\arteta_agent\\providers\\chat_completion.py tests\\test_arteta_agent_provider.py`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_provider.py -q`
  - Result: `13 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `183 passed, 3 warnings`.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `34 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `527 passed, 2 warnings`.

### Remaining

- `planner.py` still performs compatibility orchestration around pending confirmation, route, plan, Runtime, and final response composition.
- Activation already uses the provider adapter/shared client but still has its own activation-specific wrapper.
- Existing Windows asyncio/proactor resource warnings remain unrelated to this extraction.

### ECS Deployment

- Commit deployed: `d43e789 refactor: move chat provider wrapper out of planner`.
- Deployment archive: `/tmp/arteta_phase_e_provider_wrapper_d43e789.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_e_provider_wrapper_20260712032956`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/providers/chat_completion.py`;
  - `tests/test_arteta_agent_provider.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Provider Wrapper Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase B Cleanup: Move Explicit Pending Confirmation Out Of Planner

### Scope

- Added `plugins/arteta_agent/runtime/confirmation.py`.
- Moved explicit pending-action confirmation parsing and execution out of `planner.py`.
- Kept `planner.run_agent_loop(...)` behavior unchanged: it still short-circuits explicit confirmation messages before normal routing/model execution.
- `planner.py` no longer directly imports or owns:
  - `record_pending_confirmation_failure`;
  - `store_from_context`;
  - `detect_pending_action_confirmation_id(...)`;
  - `_execute_explicit_pending_action_confirmation(...)`.

### Design Decision

- Explicit confirmation is a Runtime boundary concern because it consumes a server-side pending action and must not be delegated to model reasoning.
- The new module still executes through `execute_tool_call(...)` with `ctx.extra["confirmed_action_id"]`, so existing executor checks continue to enforce user, group, tool, stored arguments, admin status, atomic consume, and audit behavior.
- The planner keeps only the orchestration decision: if the latest user message is an explicit confirmation, call the Runtime confirmation helper and return its result.

### Compatibility and Safety

- Confirmation messages such as `confirm <action_id>` and `确认 <action_id>` are still accepted.
- Missing, expired, wrong-group, wrong-user, or unknown-tool confirmations retain their existing responses.
- Explicit confirmation still avoids a model call.
- Existing audit behavior for missing confirmation and executor-level confirmed action success/failure is unchanged.

### Verification

- `python -m pytest tests/test_arteta_agent_runtime.py::test_runtime_confirmation_module_owns_explicit_pending_confirmation_helpers -q`
  - RED before implementation: failed because planner still defined the confirmation helpers.
- `python -m pytest tests/test_arteta_agent_runtime.py::test_runtime_confirmation_module_owns_explicit_pending_confirmation_helpers tests/test_arteta_agent_registry.py::test_agent_loop_executes_explicit_pending_action_confirmation tests/test_arteta_agent_registry.py::test_agent_loop_executes_explicit_pending_admin_action_confirmation tests/test_arteta_agent_registry.py::test_agent_loop_rejects_explicit_pending_action_confirmation_for_wrong_group tests/test_arteta_agent_registry.py::test_agent_loop_audits_explicit_missing_pending_confirmation -q`
  - Result: `5 passed`.
- `python -m py_compile plugins\\arteta_agent\\planner.py plugins\\arteta_agent\\runtime\\confirmation.py tests\\test_arteta_agent_runtime.py`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_runtime.py -q`
  - Result: `10 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `183 passed, 3 warnings`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `528 passed`.

### Remaining

- `planner.py` still performs compatibility orchestration around route, plan, Runtime configuration, response composition, and policy TTL finalization.
- Existing Windows asyncio/proactor resource warnings remain unrelated to this extraction.

### ECS Deployment

- Commit deployed: `4da04d5 refactor: move pending confirmation handling into runtime`.
- Deployment archive: `/tmp/arteta_phase_b_confirmation_4da04d5.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_b_confirmation_20260712033809`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/runtime/confirmation.py`;
  - `tests/test_arteta_agent_runtime.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Pending Confirmation Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase C Cleanup: Move Planned Tool Call Execution Helpers

### Scope

- Added `plugins/arteta_agent/planning/execution.py`.
- Moved planned-tool-call conversion and initial-plan execution decision helpers out of `planner.py`.
- `planner.py` now delegates to:
  - `initial_tool_calls_from_plan(...)`;
  - `should_execute_initial_plan(...)`.

### Design Decision

- Planning owns the conversion from `AgentPlan.required_tools` into OpenAI-compatible tool-call dictionaries.
- Planner should not know the details of planned call IDs or how unavailable/disabled required tools are filtered.
- Runtime execution remains unchanged; this slice only moves planning helper logic behind a clearer module boundary.

### Compatibility and Safety

- Required tools are still skipped when disabled by policy or missing from the registry.
- Multi-intent plans still execute when more than one required tool is available.
- Single required tools still execute only when plan constraints request direct execution.
- Planned call IDs remain stable: `planned-<tool-name>-<index>`.

### Verification

- `python -m pytest tests/test_arteta_agent_routing.py::test_planning_execution_module_owns_planned_tool_call_conversion -q`
  - RED before implementation: failed because planner still defined the helper functions.
- `python -m py_compile plugins\\arteta_agent\\planner.py plugins\\arteta_agent\\planning\\execution.py tests\\test_arteta_agent_routing.py`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_routing.py -q`
  - Result: `35 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `183 passed, 3 warnings`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `529 passed, 2 warnings`.

### Remaining

- `planner.py` still owns the compatibility orchestration flow: trace setup, policy TTL finalization, route/plan invocation, Runtime invocation, and final response composition.
- Existing Windows asyncio/proactor resource warnings remain unrelated to this extraction.

### ECS Deployment

- Commit deployed: `2713d9a refactor: move planned tool execution helpers`.
- Deployment archive: `/tmp/arteta_phase_c_plan_execution_2713d9a.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_c_plan_execution_20260712034504`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/planning/execution.py`;
  - `tests/test_arteta_agent_routing.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Planned Execution Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase B Cleanup: Move Runtime Service Wiring Out Of Planner

### Scope

- Added `plugins/arteta_agent/runtime/service.py`.
- Moved Runtime wiring out of `planner.py`:
  - `AgentState` construction;
  - `AgentRuntimeRunner` construction;
  - planner-to-runtime model-call adapter;
  - Runtime finalizer binding for mood emoji;
  - Runtime tool-result artifact observer;
  - loop-guard stop-message mapping for Runtime timeout/max-rounds results.
- `planner.py` now delegates to:
  - `run_runtime_loop_from_state(...)`;
  - `run_loop_from_state(...)`.

### Design Decision

- Runtime owns execution-loop wiring, budgets, state construction, finalizer binding, and tool-result observation.
- Planner keeps compatibility orchestration only: trace setup, explicit confirmation short-circuit, disabled-tool filtering, route/plan creation, and final response composition.
- `planner.call_llm_with_tools` remains the injected model-call dependency for the Runtime service. This preserves existing tests and external monkeypatch behavior while moving the Runtime implementation boundary out of planner.

### Compatibility and Safety

- `run_agent_loop(...)` signature and behavior are unchanged.
- Existing `planner.call_llm_with_tools` compatibility wrapper is still used by Runtime, so current provider behavior, OpenAI-compatible behavior, and test monkeypatches remain intact.
- Tool execution still flows through `execute_tool_call_result(...)`.
- Mood emoji sending still uses the existing response finalizer logic and policy checks.
- Artifact collection still only reads structured `ToolResult.artifacts`.

### Verification

- `python -m pytest tests/test_arteta_agent_runtime.py::test_runtime_service_owns_planner_runtime_wiring -q`
  - RED before implementation: failed because `plugins.arteta_agent.runtime.service` did not exist.
  - Result after implementation: `1 passed`.
- `python -m py_compile plugins\\arteta_agent\\planner.py plugins\\arteta_agent\\runtime\\service.py tests\\test_arteta_agent_runtime.py`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_runtime.py -q`
  - Result: `11 passed`.
- `python -m pytest tests/test_arteta_agent_runtime.py::test_runtime_runner_executes_initial_and_model_tool_calls_through_same_executor tests/test_arteta_agent_registry.py::test_agent_loop_hides_bulky_tool_categories_for_plain_chat tests/test_arteta_agent_routing.py::test_planning_execution_module_owns_planned_tool_call_conversion -q`
  - Result: `3 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `183 passed, 3 warnings`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `530 passed`.

### Remaining

- `planner.py` still owns compatibility orchestration around trace setup, policy TTL finalization, route/plan invocation, and final response composition.
- Existing Windows asyncio/proactor resource warnings remain unrelated to this extraction.

### ECS Deployment

- Commit deployed: `02a4201 refactor: move runtime service wiring`.
- Deployment archive: `/tmp/arteta_phase_b_runtime_service_02a4201.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_b_runtime_service_20260712035617`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/runtime/service.py`;
  - `tests/test_arteta_agent_runtime.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Runtime Service Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Phase F Cleanup: Move Policy Turn And Emoji Helpers Out Of Planner

### Scope

- Added `plugins/arteta_agent/policy/service.py`.
- Added `plugins/arteta_agent/policy/__init__.py`.
- Moved planner-owned policy helpers into the policy layer:
  - `has_expiring_behavior_policies(...)`;
  - `should_consume_policy_turn(...)`;
  - `consume_policy_turn_if_needed(...)`;
  - `mood_emoji_enabled(...)`.
- `planner.py` no longer imports `behavior_policy` or `consume_group_policy_turn(...)` directly.

### Design Decision

- Planner should not know how behavior-policy TTLs are stored or counted down.
- The policy service owns request-level TTL consumption decisions and exposes the simple boolean/operation boundary needed by planner.
- Emoji enablement is a behavior policy concern, so Runtime still receives a callable dependency but planner no longer reads the policy key directly.

### Compatibility and Safety

- TTL semantics are unchanged: a handled main-agent request consumes one policy turn when the group has disabled tools or expiring behavior policies.
- Permanent policies still do not decrement.
- `emoji.enabled=false` still blocks automatic mood emoji.
- Policy update tools still execute through the plan and unified Runtime path.

### Verification

- `python -m pytest tests/test_arteta_agent_behavior_policy_store.py::test_policy_service_owns_planner_policy_ttl_and_emoji_helpers -q`
  - RED before implementation: failed because `plugins.arteta_agent.policy` did not exist.
  - Result after implementation: `1 passed`.
- `python -m py_compile plugins\\arteta_agent\\planner.py plugins\\arteta_agent\\policy\\service.py tests\\test_arteta_agent_behavior_policy_store.py`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_behavior_policy_store.py tests/test_arteta_agent_mood_response.py tests/test_arteta_agent_registry.py::test_planner_records_temporary_tool_block_and_does_not_force_emoji tests/test_arteta_agent_registry.py::test_planner_turns_plain_emoji_ban_into_behavior_policy -q`
  - Result: `12 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `183 passed, 3 warnings`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `531 passed, 2 warnings`.

### Remaining

- `planner.py` still owns compatibility orchestration around trace setup, route/plan invocation, and final response composition.
- Existing Windows asyncio/proactor resource warnings remain unrelated to this extraction.

### ECS Deployment

- Commit deployed: `194905c refactor: move policy helpers out of planner`.
- Deployment archive: `/tmp/arteta_phase_f_policy_service_194905c.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_phase_f_policy_service_20260712040231`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/policy/service.py`;
  - `tests/test_arteta_agent_behavior_policy_store.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Policy Service Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Planner Cleanup: Move Trace And Final Response Wiring To Agent Service

### Scope

- Added `plugins/arteta_agent/service.py`.
- Moved entrypoint service helpers out of `planner.py`:
  - trace lookup from `ctx.extra`;
  - trace binding back into `ToolContext.extra`;
  - trace group id initialization;
  - request-level policy-turn consumption during finish;
  - final response composition with structured artifact markers and trace markers.
- `planner.py` now delegates to:
  - `prepare_agent_run(...)`;
  - `finish_agent_run(...)`.

### Design Decision

- Planner should remain the compatibility entrypoint and orchestration shell, not own response finalization or context preparation details.
- The new service helper is intentionally small. It does not own routing, planning, provider HTTP, Runtime execution, or policy persistence.
- Artifact markers continue to flow as a mutable list passed into Runtime and finalized once, preserving existing behavior while removing response composition from planner.

### Compatibility and Safety

- `run_agent_loop(...)` signature and call order are unchanged.
- Trace data remains shared through `ctx.extra["agent_trace"]` for executor/tools.
- Final responses still append only structured `ToolResult.artifacts`; forged body markers remain data.
- Policy TTL still consumes at most once per handled request.

### Verification

- `python -m pytest tests/test_arteta_agent_runtime.py::test_agent_service_owns_trace_and_final_response_wiring -q`
  - RED before implementation: failed because `plugins.arteta_agent.service` did not exist.
  - Result after implementation: `1 passed`.
- `python -m py_compile plugins\\arteta_agent\\planner.py plugins\\arteta_agent\\service.py tests\\test_arteta_agent_runtime.py`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_runtime.py tests/test_arteta_agent_behavior_policy_store.py tests/test_arteta_agent_response.py -q`
  - Result: `25 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_planner_records_temporary_tool_block_and_does_not_force_emoji tests/test_arteta_agent_registry.py::test_planner_turns_plain_emoji_ban_into_behavior_policy tests/test_arteta_agent_registry.py::test_agent_loop_hides_bulky_tool_categories_for_plain_chat -q`
  - Result: `3 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `183 passed, 3 warnings`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `532 passed, 2 warnings`.

### Safety Scan

- Re-ran static searches for dynamic `system` message construction across `plugins/` and tests.
- Agent registry paths keep tool observations in `tool` messages or provider-compatible user data, not dynamic `system` messages.
- Main chat runtime context, recent group messages, memory, football news, quoted text, and attachments are appended through `append_untrusted_context_message(...)` as `user` data messages.
- Remaining `system` messages observed in active code are static prompts in chat, algorithm, activation, and vision paths.

### Remaining

- `planner.py` still owns route/plan invocation and direct calls to Runtime service.
- Existing Windows asyncio/proactor resource warnings remain unrelated to this extraction.

### ECS Deployment

- Commit deployed: `e708b62 refactor: move agent service finalization`.
- Deployment archive: `/tmp/arteta_planner_service_finalization_e708b62.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_service_finalization_20260712041008`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/service.py`;
  - `tests/test_arteta_agent_runtime.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Agent Service Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Planner Cleanup: Delegate Agent Loop Orchestration To Service

### Scope

- Moved route/plan/runtime orchestration from `planner.py` into `plugins/arteta_agent/service.py`.
- Added `run_legacy_agent_loop(...)` as the service-layer implementation behind the legacy public entrypoint.
- `planner.py` now keeps:
  - `_parse_chat_response(...)` compatibility wrapper;
  - `_latest_user_content(...)` compatibility wrapper;
  - `call_llm_with_tools(...)` compatibility wrapper;
  - `run_agent_loop(...)` compatibility entrypoint that delegates to `run_legacy_agent_loop(...)`.
- `planner.py` is now 55 lines and no longer imports routing, planning, Runtime runner service, registry, contextual tool filtering, response composer, or policy helpers directly.

### Design Decision

- `run_agent_loop(...)` remains the public compatibility entrypoint for existing callers.
- The planner still injects `planner.call_llm_with_tools` into the service. This preserves existing tests and downstream monkeypatch behavior while removing orchestration from planner.
- `run_legacy_agent_loop(...)` intentionally lives in the service layer first, rather than introducing a larger request object in the same commit. This keeps the final planner-thinning step reviewable and reversible.

### Compatibility and Safety

- Public function signatures are unchanged.
- Existing `planner.call_llm_with_tools` monkeypatch behavior is preserved.
- Explicit pending confirmation, disabled tool filtering, contextual exclusions, multi-intent planning, Runtime execution, structured artifact finalization, trace response, and mood emoji policy still execute in the same order.

### Verification

- `python -m pytest tests/test_arteta_agent_runtime.py::test_planner_delegates_agent_loop_orchestration_to_service -q`
  - RED before implementation: failed because `service.run_legacy_agent_loop` did not exist.
  - Result after implementation: `1 passed`.
- `python -m py_compile plugins\\arteta_agent\\planner.py plugins\\arteta_agent\\service.py tests\\test_arteta_agent_runtime.py`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_runtime.py tests/test_arteta_agent_routing.py -q`
  - Result: `48 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_hides_bulky_tool_categories_for_plain_chat tests/test_arteta_agent_registry.py::test_planner_records_temporary_tool_block_and_does_not_force_emoji tests/test_arteta_agent_registry.py::test_agent_loop_records_rounds_and_tool_trace tests/test_arteta_agent_registry.py::test_agent_loop_preserves_grok_snapshot_artifact_from_tool_result -q`
  - Result: `4 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `183 passed, 3 warnings`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `533 passed, 2 warnings`.

### Remaining

- The service layer still uses a legacy parameter list matching `run_agent_loop(...)`; a future low-risk cleanup can introduce an `AgentRequest` object.
- Existing Windows asyncio/proactor resource warnings remain unrelated to this extraction.

### ECS Deployment

- Commit deployed: `ff0b3c7 refactor: delegate agent loop to service`.
- Deployment archive: `/tmp/arteta_planner_delegate_service_ff0b3c7.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_planner_delegate_service_20260712041613`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/service.py`;
  - `tests/test_arteta_agent_runtime.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Planner Delegation Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Planner Cleanup: Introduce AgentRequest Service Entrypoint

### Scope

- Added structured `AgentRequest` to `plugins/arteta_agent/service.py`.
- Added `run_agent_request(...)` as the primary service-layer entrypoint.
- Kept `run_legacy_agent_loop(...)` as a compatibility wrapper that builds an `AgentRequest`.
- Updated `planner.run_agent_loop(...)` to construct `AgentRequest` and delegate to `run_agent_request(...)`.

### Design Decision

- `planner.py` now matches the intended compatibility-entrypoint shape without changing its public function signature.
- The model-call dependency remains explicit in `AgentRequest`, preserving `planner.call_llm_with_tools` monkeypatch compatibility and avoiding provider coupling inside the service layer.
- The legacy wrapper remains in the service layer for now so any internal callers can migrate without a flag day.

### Compatibility and Safety

- Public `run_agent_loop(...)` and `call_llm_with_tools(...)` signatures are unchanged.
- No routing, planning, Runtime, policy, provider, permission, or artifact behavior changed.
- Existing explicit confirmation and multi-intent plan execution order is unchanged.

### Verification

- `python -m pytest tests/test_arteta_agent_runtime.py::test_planner_uses_structured_agent_request_for_service_entrypoint -q`
  - RED before implementation: failed because `service.AgentRequest` did not exist.
  - Result after implementation: passed as part of the Runtime suite.
- `python -m pytest tests/test_arteta_agent_runtime.py -q`
  - Result: `14 passed`.
- `python -m py_compile plugins\\arteta_agent\\planner.py plugins\\arteta_agent\\service.py tests\\test_arteta_agent_runtime.py`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_hides_bulky_tool_categories_for_plain_chat tests/test_arteta_agent_registry.py::test_planner_records_temporary_tool_block_and_does_not_force_emoji tests/test_arteta_agent_registry.py::test_agent_loop_preserves_grok_snapshot_artifact_from_tool_result -q`
  - Result: `3 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `183 passed, 3 warnings`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `534 passed, 2 warnings`.

### Remaining

- `run_legacy_agent_loop(...)` can be removed after confirming there are no internal callers left outside planner.
- Existing Windows asyncio/proactor resource warnings remain unrelated to this extraction.

### ECS Deployment

- Commit deployed: `3483399 refactor: add agent request service entrypoint`.
- Deployment archive: `/tmp/arteta_agent_request_entrypoint_3483399.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_request_entrypoint_20260712042255`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/planner.py`;
  - `plugins/arteta_agent/service.py`;
  - `tests/test_arteta_agent_runtime.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After AgentRequest Deploy

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Planner Cleanup: Remove Legacy Agent Loop Wrapper

### Scope

- Removed unused `run_legacy_agent_loop(...)` from `plugins/arteta_agent/service.py`.
- `run_agent_request(...)` is now the only service-layer Agent loop entrypoint.
- Updated the planner structure tests to assert the legacy wrapper is gone.

### Design Decision

- Static search showed no callers for `run_legacy_agent_loop(...)` outside its own definition.
- Removing the wrapper avoids leaving a second service entrypoint that could drift from `AgentRequest`.
- `planner.run_agent_loop(...)` remains the only legacy public compatibility entrypoint.

### Compatibility and Safety

- Public `planner.run_agent_loop(...)` signature is unchanged.
- No runtime execution order, permissions, routing, planning, provider, trace, artifact, or policy behavior changed.

### Verification

- `python -m pytest tests/test_arteta_agent_runtime.py::test_agent_service_has_no_unused_legacy_loop_wrapper -q`
  - RED before implementation: failed because `service.py` still defined `run_legacy_agent_loop(...)`.
  - Result after implementation: passed as part of the Runtime suite.
- `python -m pytest tests/test_arteta_agent_runtime.py -q`
  - Result: `15 passed`.
- `python -m py_compile plugins\\arteta_agent\\planner.py plugins\\arteta_agent\\service.py tests\\test_arteta_agent_runtime.py`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `183 passed, 3 warnings`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `535 passed, 2 warnings`.

### Remaining

- Existing Windows asyncio/proactor resource warnings remain unrelated to this cleanup.

### ECS Deployment

- Commit deployed: `4a4e210 refactor: remove legacy agent loop wrapper`.
- Deployment archive: `/tmp/arteta_remove_legacy_loop_wrapper_4a4e210.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_remove_legacy_loop_wrapper_20260712042745`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/service.py`;
  - `tests/test_arteta_agent_runtime.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Legacy Wrapper Removal

- `python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Provider Cleanup: Reuse Shared HTTP Client In Agent Tools

### Scope

- Closed the remaining Agent-tool HTTP lifecycle gap found during final acceptance audit.
- Kept the slice limited to `plugins/arteta_agent/tools/web_access.py`, `document.py`, and `image.py`.

### Changes

- Replaced direct `httpx.AsyncClient(...)` creation in Agent web/document/image tools with the shared provider client lifecycle:
  - `web_access` search/fetch/Grok/X helpers now call `get_shared_async_client()` through a local `_http_client()` boundary.
  - `document._fetch_binary(...)` now streams through the shared client while preserving per-request headers, redirects, timeout, and byte limits.
  - `image._request_generated_image(...)` now uses the shared client for both image-generation POST and returned-image GET.
- Updated redirect and byte-limit tests to monkeypatch the tool `_http_client()` dependency instead of patching `httpx.AsyncClient`.
- Added provider tests proving:
  - Agent HTTP tools no longer directly instantiate `httpx.AsyncClient`;
  - web fetch helpers reuse the same shared client instance across calls.

### Design Decision

- The application-level shared client remains the single place that creates `httpx.AsyncClient`.
- Tool-specific timeout, headers, redirects, and streaming behavior stay on each request call, so behavior is preserved while connection lifecycle is centralized.
- Local `_http_client()` wrappers keep tests and future dependency injection explicit without coupling tools to provider internals beyond the shared lifecycle API.

### Compatibility and Safety

- Public tool names, schemas, permissions, artifact behavior, URL safety checks, final redirect checks, and byte-limit streaming behavior are unchanged.
- Shutdown still uses the existing `driver.on_shutdown(close_shared_async_client)` hook.
- No dynamic system-message path was introduced; static scan still shows only `plugins/arteta_agent/providers/http_client.py` creates `httpx.AsyncClient`.

### Verification

- `python -m py_compile plugins\\arteta_agent\\tools\\web_access.py plugins\\arteta_agent\\tools\\document.py plugins\\arteta_agent\\tools\\image.py tests\\test_arteta_agent_provider.py tests\\test_arteta_agent_registry.py`
  - Result: passed.
- `python -m pytest tests/test_arteta_agent_provider.py -q`
  - Result: `15 passed`.
- `python -m pytest tests/test_arteta_agent_runtime.py tests/test_arteta_agent_provider.py -q`
  - Result: `30 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `183 passed, 3 warnings`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python tools\\verify_features.py --suite chat`
  - Result: passed.
- `python tools\\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.
- `python -m pytest tests -q`
  - Result: `537 passed, 1 warning`.

### Risk Notes

- The remaining local warning is the pre-existing Windows asyncio/proactor cleanup warning family; this slice reduced rather than added warning count in the full test run.
- Non-Agent legacy modules still have their own historical HTTP clients. This slice only closes the Agent architecture acceptance boundary for Provider/Activation/Agent tools.

### Remaining

- No remaining work for this HTTP-client lifecycle slice.

### ECS Deployment

- Commit deployed: `ace82b8 refactor: reuse shared client in agent tools`.
- Deployment archive: `/tmp/arteta_agent_shared_client_ace82b8.tar.gz` on ECS.
- Remote backup directory: `/opt/arteta_bot/backups/agent_shared_http_client_20260712103302`.
- Remote `py_compile` passed for:
  - `plugins/arteta_agent/tools/document.py`;
  - `plugins/arteta_agent/tools/image.py`;
  - `plugins/arteta_agent/tools/web_access.py`;
  - `tests/test_arteta_agent_provider.py`;
  - `tests/test_arteta_agent_registry.py`.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.

### ECS Smoke After Shared HTTP Client Deploy

- `./venv/bin/python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `./venv/bin/python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `./venv/bin/python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 - Final Acceptance Audit: PendingAction, Validation, Provider Fallback, Plan Dependencies

### Scope

- Performed final acceptance audit without adding new product behavior.
- Checked commit/deploy consistency, PendingAction atomicity, handler-before-validation safety, provider fallback prompt-injection safety, explicit plan dependencies, concurrency metadata, TTL boundaries, and local warning cleanliness.

### Findings And Fixes

- PendingAction consumption already used `BEGIN IMMEDIATE` with SELECT and DELETE in a single SQLite transaction; added a concurrent confirmation regression test.
- Tool argument validation already ran before permission checks and handler execution; added parameterized coverage for required fields, types, extra fields, enum, length, array size, invalid JSON, and non-object roots.
- Provider fallback for models without standard tool-role history already kept tool data out of `system`; added a prompt-injection regression test for untrusted tool-result wrapping.
- Found a real gap: plans had only ordered required tools, so Runtime could parallelize a web verification call before its document-read dependency completed. Added `AgentPlan.dependencies`, `initial_tool_dependencies_from_plan(...)`, `AgentRunConfig.tool_call_dependencies`, and Runtime batching checks.
- Found a metadata gap: parallel execution had no explicit shared-resource grouping. Added `ToolSpec.concurrency_group`, defaulting to serial-safe behavior unless tools explicitly opt into parallel execution.
- Found local test cleanup noise: Grok search-path tests could indirectly start Playwright snapshot capture and leave Windows asyncio subprocess cleanup warnings. Isolated snapshot side effects in tests while keeping dedicated snapshot tests intact.

### Design Decisions

- Dependencies are expressed at planning level by tool name and converted to concrete `tool_call_id` dependencies at runtime entry. Runtime remains routing-agnostic.
- Current-fact routing still defaults to `grok_search`; document + current-fact plans attach the dependency to the actual rewritten public-current-fact tool.
- Runtime parallel batches require safe-read permission, explicit `parallel_safe=True`, `idempotent=True`, no unmet dependency, and no duplicate non-empty `concurrency_group` within the batch.
- Test isolation avoids real browser startup in non-snapshot tests; production browser reuse and shutdown behavior are unchanged.

### Compatibility And Safety

- Public entrypoint `run_agent_loop` remains unchanged.
- Tool names, schemas, permissions, PendingAction binding, Provider behavior, response composition, and ECS deployment flow are unchanged.
- No dynamic system-message path was added.
- The new `ToolSpec.concurrency_group` field is optional and defaults to `None`, preserving existing registrations.

### Verification

- Required audit commands:
  - `git log --oneline --decorate -15`
    - Top deployed code lineage before this fix included `ace82b8 refactor: reuse shared client in agent tools`, with docs-only commits after it.
  - `git diff ace82b8..HEAD -- plugins/arteta_agent tests`
    - Before this audit fix: empty, proving docs-only HEAD after `ace82b8` had no extra Agent/test code.
  - `git merge-base --is-ancestor 4a4e210 ace82b8`
    - Result: true; `4a4e210` is an ancestor of `ace82b8`, so the `ace82b8` deployment included the legacy-wrapper removal commit.
- RED checks before implementation:
  - Dependent tools could be batched because `AgentRunConfig.tool_call_dependencies` did not exist.
  - Same-resource tools could not declare a `concurrency_group`.
  - Plan dependencies could not be converted into runtime `tool_call_id` dependencies.
- `python -m pytest tests/test_arteta_agent_registry.py::test_executor_concurrent_pending_action_confirmation_consumes_once tests/test_arteta_agent_registry.py::test_executor_rejects_invalid_arguments_before_permission_or_handler tests/test_arteta_agent_provider.py::test_limited_provider_tool_history_wraps_prompt_injection_as_untrusted_data tests/test_arteta_agent_behavior_policy_store.py::test_policy_ttl_boundary_scenarios tests/test_arteta_agent_runtime.py::test_runtime_runner_does_not_parallelize_dependent_tool_calls tests/test_arteta_agent_runtime.py::test_runtime_runner_does_not_parallelize_same_concurrency_group tests/test_arteta_agent_routing.py::test_plan_builder_marks_document_verification_dependency -q`
  - Result: `22 passed`.
- `python -m pytest tests/test_arteta_agent_runtime.py tests/test_arteta_agent_routing.py tests/test_arteta_agent_provider.py tests/test_arteta_agent_behavior_policy_store.py -q`
  - Result: `84 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q -W error::pytest.PytestUnraisableExceptionWarning`
  - Result: `192 passed`.
- `python -m pytest tests -q`
  - Result: `559 passed`.
- `python tools\\verify_features.py --suite agent_loop`
  - Result: passed.
- `python tools\\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.

### Risk Notes

- No configured ruff/mypy/pyright/flake8 entry was found in `pyproject.toml`, `setup.cfg`, `tox.ini`, or `.github`; `compileall` is the available static syntax check.
- Legacy non-Agent modules remain outside this acceptance boundary.

### Remaining

- No remaining work for this final acceptance audit slice.

### ECS Deployment

- Final audit fix commit deployed to ECS from a focused local archive; see `git log` and the final acceptance report for the exact hash.
- Deployment archive pattern: `/tmp/arteta_final_acceptance_<commit>.tar.gz` on ECS.
- Remote backup directory pattern: `/opt/arteta_bot/backups/agent_final_acceptance_<commit>_<timestamp>`.
- Remote `compileall` passed for:
  - `plugins/arteta_agent`;
  - updated Agent architecture tests.
- Restarted `arteta_bot` and `arteta_dashboard`.
- `supervisorctl status arteta_bot arteta_dashboard`
  - Result: both `RUNNING`.
- Remote source check confirmed deployed files contain:
  - `ToolSpec.concurrency_group`;
  - Runtime `concurrency_groups` batching guard;
  - `test_runtime_runner_does_not_parallelize_same_concurrency_group`.

### ECS Smoke After Final Audit Deploy

- `./venv/bin/python tools/verify_features.py --suite chat`
  - Result: passed on ECS.
- `./venv/bin/python tools/verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed on ECS.
- `./venv/bin/python tools/verify_features.py --suite agent_loop`
  - Result: passed on ECS.

## 2026-07-12 Web Access Round 1 Safety Slice

### Scope

- Revised `docs/tasks/rebulid_webaccess.md` from a broad one-shot rewrite into a three-round execution plan:
  - Round 1: Web safety and safe-read side-effect cleanup.
  - Round 2: ToolResult protocol and factual verification.
  - Round 3: module split and search backend abstraction.
- Kept Round 1 limited to `plugins/arteta_agent/tools/web_access.py` behavior and direct tests.
- Did not introduce new `ToolResult.success()`, `ToolResult.error()`, `Artifact`, or `data` APIs.
- Did not split `web_access.py` yet.

### Changes

- Added DNS-aware best-effort URL validation before `_fetch_url()` sends a request:
  - rejects URL credentials;
  - enforces URL length and default 80/443 ports;
  - rejects localhost, private, loopback, link-local, reserved, multicast, unspecified, non-global, single-label, `.local`, `.internal`, and `.lan` targets;
  - resolves A/AAAA via `socket.getaddrinfo()` and rejects if any resolved IP is non-global.
- Changed `_fetch_url()` to disable automatic redirects and manually revalidate each redirect target before requesting the next hop.
- Added direct text Content-Type allowlist and early `Content-Length` oversize rejection.
- Kept existing streaming byte limit and added `truncated` metadata to `_fetch_url()` results.
- Removed implicit Grok source snapshot creation from:
  - `web_search`;
  - `grok_search`;
  - `verify_recent_claim`.
- Disabled automatic redirect following for Web backend HTTP calls, including:
  - Bing HTML search;
  - DuckDuckGo HTML search;
  - Jina search fetch;
  - GrokSearch API calls;
  - X Fetch Bridge;
  - X syndication;
  - X mirror fetches.
- Kept legacy snapshot helper functions available for explicit link-analysis paths and existing direct tests.
- Tightened Web tool schemas with explicit `additionalProperties: false`, string length bounds, numeric min/max, and URL length limits.
- Added explicit concurrency metadata on Web safe-read tools:
  - `parallel_safe=True`;
  - `concurrency_group="web_http"`;
  - `idempotent=True`.
- Removed task-specific entity boosts from `_claim_result_score()` and changed `verify_recent_claim` wording to “candidate source” rather than implying a verdict.

### Design Decisions

- `_safe_url()` remains a lightweight synchronous syntax/local-address filter because it is used by parsing and formatting paths.
- `_fetch_url()` is the actual network boundary and now performs DNS-aware validation immediately before each outbound request.
- This is still application-layer best-effort SSRF protection; production ECS/container egress rules remain required for stronger guarantees.
- Search tools no longer create screenshot artifacts implicitly because they are registered as `safe_read`.
- `verify_recent_claim` remains a candidate-evidence collector in Round 1; support/refute/unclear belongs to Round 2.

### RED Checks Before Implementation

- `test_fetch_url_rejects_dns_resolving_to_private_ip_before_request` failed because `_fetch_url()` sent the HTTP request after only syntactic host checks.
- `test_fetch_url_revalidates_each_redirect_before_request` failed because `_fetch_url()` used `follow_redirects=True`.
- `test_web_search_does_not_append_grok_snapshot_marker` failed because `web_search()` called `_grok_source_snapshot_marker()`.
- `test_web_tool_registration_has_schema_bounds_and_explicit_parallel_metadata` failed because Web schemas lacked bounds and Web tools lacked explicit parallel metadata.
- `test_verify_recent_claim_does_not_claim_verdict_for_single_candidate` failed because the tool said “已找到可核查来源”.
- `test_claim_ranking_has_no_task_specific_entity_hardcodes` failed because `_claim_result_score()` still contained old task entities.

### Verification

- `python -m pytest tests/test_arteta_agent_web_security.py -q`
  - Result: `7 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `192 passed`.
- `python -m pytest tests/test_arteta_agent_web_security.py tests/test_arteta_agent_registry.py -q`
  - Result: `199 passed`.
- `python -m pytest tests/test_arteta_agent_runtime.py tests/test_arteta_agent_routing.py tests/test_arteta_agent_provider.py -q`
  - Result: `69 passed`.
- `python -m pytest tests -q`
  - Result: `566 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "follow_redirects=True|dict\[|list\[|set\[|tuple\[|\| None|None \|" plugins/arteta_agent/tools/web_access.py tests/test_arteta_agent_web_security.py docs/tasks/rebulid_webaccess.md`
  - Result: no matches.

### Python 3.8 Check

- `python3.8 -m py_compile plugins/arteta_agent/tools/web_access.py`
  - Result: could not run locally; `python3.8` is not installed.
- `py -3.8 -m py_compile plugins/arteta_agent/tools/web_access.py`
  - Result: could not run locally; Windows launcher reports only Python 3.10 and 3.13 installed.
- Local mitigation: compileall passed under Python 3.10 and grep found no Python 3.9/3.10 generic/union syntax in touched Round 1 files.

### Risk Notes

- DNS-aware validation uses `socket.getaddrinfo()` before `httpx` connects; it reduces common SSRF paths but does not eliminate DNS rebinding.
- `_fetch_url()` tests now need explicit DNS stubs when using fake public hostnames.
- Existing direct snapshot helper tests remain because Round 1 only removes implicit search side effects; full artifact protocol cleanup remains Round 2.

### Remaining

- Round 1 still needs broader coverage for unsupported Content-Type, URL credentials, illegal ports, redirect count, and handler-before-schema rejection on actual Web specs.
- Round 2 remains open:
  - structured `ToolResult` protocol design;
  - marker-forgery hardening;
  - support/refute/unclear factual verification;
  - remote fetch proxy policy and sensitive URL handling.
- Round 3 remains open:
  - module split;
  - `SearchBackend` abstraction;
  - X provenance cleanup;
  - structured logging/observability cleanup.

## 2026-07-12 Web Access Round 2 ToolResult Protocol Slice

### Scope

- Started Round 2 with the executor protocol boundary before migrating individual Web tools.
- Kept existing `ToolResult` dataclass shape; did not add `ToolResult.success()`, `ToolResult.error()`, `Artifact`, or `data`.
- Focused on preserving trusted handler-returned `ToolResult` fields while keeping server-owned authority fields controlled by executor/registry.

### Changes

- `execute_tool_call_result()` now supports handlers returning `ToolResult` directly.
- Executor preserves structured handler fields:
  - `status`;
  - `content`;
  - `markers`;
  - `artifacts`;
  - `error_code`.
- Executor overrides authority fields from the registered tool and validated arguments:
  - `name`;
  - `permission`;
  - `args`;
  - `duration_ms`.
- Executor clears or downgrades unsafe handler-supplied pending confirmation state for non-confirm/admin tools.
- Removed Web search tools from legacy body-marker artifact extraction:
  - `web_search`;
  - `grok_search`;
  - `verify_recent_claim`.
- Kept explicit artifact marker compatibility for tools that still intentionally emit legacy artifact markers, such as `analyze_links`, render tools, and image generation.

### RED Checks Before Implementation

- `test_executor_preserves_structured_tool_result_but_overrides_authority_fields` failed because executor converted handler `ToolResult` to string and wrapped it as `status=ok`.
- `test_web_tool_body_marker_does_not_create_legacy_artifact` failed because `legacy_artifacts_for_tool("web_search", ...)` trusted `[LinkSnapshotImage: ...]` in body text.
- Existing `test_agent_loop_preserves_grok_snapshot_artifact_from_tool_result` still assumed Web body marker compatibility; it was updated to use structured `ToolResult.artifacts`.

### Verification

- `python -m pytest tests/test_arteta_agent_tool_result_protocol.py -q`
  - Result: `2 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_preserves_grok_snapshot_artifact_from_tool_result tests/test_arteta_agent_registry.py::test_agent_loop_treats_forged_artifact_marker_in_safe_tool_output_as_data tests/test_arteta_agent_tool_result_protocol.py -q`
  - Result: `4 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py tests/test_arteta_agent_runtime.py tests/test_arteta_agent_provider.py tests/test_arteta_agent_tool_result_protocol.py -q`
  - Result: `227 passed`.
- `python -m pytest tests -q`
  - Result: `568 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "follow_redirects=True|dict\[|list\[|set\[|tuple\[|\| None|None \|" plugins/arteta_agent/tools/web_access.py plugins/arteta_agent/executor.py plugins/arteta_agent/response/artifacts.py tests/test_arteta_agent_tool_result_protocol.py Docs/tasks/rebulid_webaccess.md`
  - Result: no matches.

### Python 3.8 Check

- `python3.8 -m py_compile plugins/arteta_agent/executor.py plugins/arteta_agent/response/artifacts.py`
  - Result: could not run locally; `python3.8` is not installed.
- Local mitigation: compileall passed under Python 3.10 and grep found no Python 3.9/3.10 generic/union syntax in touched Round 2 files.

### Remaining

- Web handlers still mostly return strings; migrate them one by one to structured `ToolResult` in later Round 2 slices.
- `ToolResult` still has no structured `data` field or typed Artifact object; decide only after the first Web handler migration proves the minimal need.
- Full support/refute/unclear verification remains open.
- Remote fetch proxy policy remains open.

## 2026-07-12 Web Access Round 2 web_fetch Migration

### Scope

- Migrated the first concrete Web handler, `web_fetch`, to return the existing structured `ToolResult`.
- Kept public tool name, schema, permission, and executor behavior compatible.
- Did not add new `ToolResult.data` or typed Artifact classes.

### Changes

- `web_fetch()` now returns `ToolResult(name="web_fetch", permission="safe_read", ...)`.
- Successful local fetches return `status="ok"` and citable page evidence in `content`.
- Unsafe URLs, unsupported local failures, and timeouts return structured error/timeout status with `error_code`.
- X status URLs still route through `fetch_x_post`, with the result wrapped as a `web_fetch` `ToolResult`.
- Remote Grok `web_fetch` proxy is no longer used merely because GrokSearch is configured.
- Remote fetch proxy requires explicit `ARTETA_ALLOW_REMOTE_FETCH_PROXY` opt-in and is only attempted after local fetch fails.
- `tools/verify_features.py` now reads `ToolResult.content` for offline Web access checks.

### RED Checks Before Implementation

- `test_web_fetch_returns_structured_tool_result` failed because `web_fetch()` returned a plain string.
- `test_web_fetch_does_not_use_remote_grok_proxy_by_default` failed because the old behavior could use Grok fetch whenever configured.
- Existing direct `web_fetch` registry tests failed after implementation until updated to assert `ToolResult.status` and `ToolResult.content`.
- `test_agent_registry_web_access_offline_ignores_live_grok_env` failed until `verify_features.py` was updated for structured `web_fetch` output.

### Verification

- `python -m pytest tests/test_arteta_agent_tool_result_protocol.py::test_web_fetch_returns_structured_tool_result tests/test_arteta_agent_tool_result_protocol.py::test_web_fetch_does_not_use_remote_grok_proxy_by_default -q`
  - Result: `2 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `192 passed`.
- `python -m pytest tests/test_arteta_agent_tool_result_protocol.py tests/test_arteta_agent_web_security.py tests/test_arteta_agent_provider.py tests/test_arteta_agent_runtime.py tests/test_arteta_agent_registry.py -q`
  - Result: `236 passed`.
- `python -m pytest tests/test_verify_features.py::VerifyFeaturesTests::test_agent_registry_web_access_offline_ignores_live_grok_env -q`
  - Result: `1 passed`.
- `python -m pytest tests -q`
  - Result: `570 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "follow_redirects=True|dict\[|list\[|set\[|tuple\[|\| None|None \|" plugins/arteta_agent/tools/web_access.py tests/test_arteta_agent_tool_result_protocol.py tools/verify_features.py`
  - Result: no matches.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.

### Remaining

- Migrate `web_search`, `grok_search`, `fetch_x_post`, and `verify_recent_claim` to structured `ToolResult`.
- Add sensitive URL checks before any allowed remote fetch proxy call.
- Implement real multi-source `support/refute/unclear` verification.

## 2026-07-12 Web Access Round 2 Claim Verification Verdict

### Scope

- Migrated `verify_recent_claim` to structured `ToolResult`.
- Implemented the first conservative multi-source `support/refute/unclear` verdict path.
- Kept implementation inside `web_access.py`; extraction to `tools/web/verification.py` remains Round 3.

### Changes

- Added internal `_VerificationEvidence` model and verification helpers.
- `verify_recent_claim()` now:
  - searches candidates;
  - de-duplicates by domain;
  - fetches up to 3 independent candidate pages;
  - classifies fetched page text as `support`, `refute`, or `unclear`;
  - refuses to confirm based only on search snippets;
  - returns `ToolResult` with verdict markers: `supported`, `refuted`, or `unclear`.
- Verdict policy:
  - one official/authoritative support with no authoritative refute -> supported;
  - one official/authoritative refute with no authoritative support -> refuted;
  - authoritative support and refute conflict -> unclear;
  - only ordinary sources -> unclear;
  - fetch failures with only snippets -> unclear.
- `tools/verify_features.py` now reads structured `verify_recent_claim.content` and stores text in report details.

### RED Checks Before Implementation

- `test_verify_recent_claim_supported_by_official_source` failed because the handler returned a string and did not produce verdict markers.
- `test_verify_recent_claim_refuted_by_official_source` failed because there was no refutation verdict path.
- `test_verify_recent_claim_unclear_with_single_ordinary_source` failed because the old flow selected a best candidate rather than evaluating source strength.
- `test_verify_recent_claim_unclear_when_authoritative_sources_conflict` failed because only one source was evaluated.
- `test_verify_recent_claim_does_not_trust_search_snippet_only` failed because fetch failures still rendered snippets as candidate evidence without a formal unclear verdict.

### Verification

- `python -m pytest tests/test_arteta_agent_web_verification.py -q`
  - Result: `5 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py -q`
  - Result: `192 passed`.
- `python -m pytest tests/test_arteta_agent_web_verification.py tests/test_arteta_agent_tool_result_protocol.py tests/test_arteta_agent_web_security.py tests/test_arteta_agent_registry.py -q`
  - Result: `208 passed`.
- `python -m pytest tests/test_verify_features.py::VerifyFeaturesTests::test_agent_registry_web_access_offline_ignores_live_grok_env -q`
  - Result: `1 passed`.
- `python -m pytest tests -q`
  - Result: `575 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "follow_redirects=True|dict\[|list\[|set\[|tuple\[|\| None|None \|" plugins/arteta_agent/tools/web_access.py tests/test_arteta_agent_web_verification.py tools/verify_features.py`
  - Result: no matches.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.

### Risk Notes

- The stance classifier is intentionally conservative and rule-based. It handles direct support/refute phrasing and obvious negation, not arbitrary natural-language entailment.
- Ordinary source support remains `unclear`, even when text appears to support the claim.
- Full LLM-assisted stance classification, if needed, should be designed separately with JSON-only output and untrusted-data wrapping.

### Remaining

- Migrate `web_search`, `grok_search`, and `fetch_x_post` to structured `ToolResult`.
- Add sensitive URL checks before an explicitly enabled remote fetch proxy call.
- Move verification models and helpers out of `web_access.py` during Round 3.

## 2026-07-12 Web Access Round 2 Search ToolResult Migration

### Scope

- Migrated `web_search` and `grok_search` direct handler returns to structured `ToolResult`.
- Kept public tool names and human-readable content stable.
- Preserved legacy `[grok]` text prefix for compatibility while also exposing `[grok]` through trusted `ToolResult.markers`.

### Changes

- `web_search()` now returns:
  - `status="ok"` on successful search;
  - `status="error"` with `error_code="EmptyQuery"` for empty queries;
  - `status="timeout"` with `error_code="TimeoutError"` for search timeout;
  - `status="error"` with the exception class name for other backend failures.
- `grok_search()` now returns:
  - `status="ok"` with `[grok]` marker on successful GrokSearch;
  - `status="unavailable"` with `error_code="GrokSearchNotConfigured"` when GrokSearch credentials are absent;
  - structured timeout and backend error states.
- Updated direct-call registry and security tests to inspect `ToolResult.content`, `ToolResult.status`, and `ToolResult.markers` instead of relying on raw strings.

### Compatibility

- The formatted search body remains unchanged for model-facing content.
- The `[grok]` prefix remains in `content` for existing text consumers.
- Trusted marker extraction no longer depends on parsing untrusted tool body text.

### Verification

- `python -m pytest tests/test_arteta_agent_registry.py tests/test_arteta_agent_web_security.py tests/test_arteta_agent_tool_result_protocol.py -q`
  - Result: `205 passed`.
- `python -m pytest tests -q`
  - Result: `577 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "\b(dict|list|set|tuple)\[|\|\s*None|None\s*\|" plugins/arteta_agent/tools/web_access.py tests/test_arteta_agent_tool_result_protocol.py tests/test_arteta_agent_registry.py tests/test_arteta_agent_web_security.py`
  - Result: no matches.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.

### Remaining

- Migrate `fetch_x_post` to structured `ToolResult`.
- Add sensitive URL checks before an explicitly enabled remote fetch proxy call.
- Move search and verification helpers out of `web_access.py` during Round 3.

## 2026-07-12 Web Access Round 2 X Fetch ToolResult Migration

### Scope

- Migrated `fetch_x_post` direct handler returns to structured `ToolResult`.
- Preserved the existing human-readable `[x-post]`, `[grok]`, and `[x-post-unavailable]` content prefixes for compatibility.
- Added an explicit DNS-aware validation gate before the optional Grok remote fetch proxy can receive a URL after local fetch failure.

### Changes

- `fetch_x_post()` now returns:
  - `status="ok"` with marker `[x-post]` for X Fetch Bridge, syndication, and mirror success paths;
  - `status="ok"` with markers `[grok]` and `[x-post]` when the Grok fetch fallback supplies X post text;
  - `status="unavailable"` with `error_code="XPostUnavailable"` when all X channels fail;
  - `status="error"` with `error_code="InvalidXStatusURL"` for non-X/non-status URLs.
- `web_fetch()` now preserves structured X subtool `status`, `content`, `error_code`, and `markers` instead of inferring state from raw text.
- Before using `ARTETA_ALLOW_REMOTE_FETCH_PROXY`, `web_fetch()` revalidates the URL through `_validate_public_http_url()` so the remote proxy path cannot skip the same DNS-aware SSRF gate used by local fetch.

### RED Checks Before Implementation

- `test_fetch_x_post_returns_structured_tool_result` failed because `fetch_x_post()` still returned a raw string.
- `test_web_fetch_preserves_structured_x_post_status_and_markers` failed because `web_fetch()` dropped structured markers from an X subtool result.
- `test_web_fetch_revalidates_url_before_remote_fetch_proxy` failed because the remote proxy path did not call the DNS-aware validator before `_groksearch_fetch()`.

### Verification

- `python -m pytest tests/test_arteta_agent_tool_result_protocol.py -q`
  - RED result before implementation: `3 failed, 6 passed`.
  - GREEN result after implementation: `9 passed`.
- `python -m pytest tests/test_arteta_agent_tool_result_protocol.py tests/test_arteta_agent_registry.py tests/test_arteta_agent_web_security.py -q`
  - Result: `208 passed`.
- `python -m pytest tests -q`
  - Result: `580 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "\b(dict|list|set|tuple)\[|\|\s*None|None\s*\|" plugins/arteta_agent/tools/web_access.py tests/test_arteta_agent_tool_result_protocol.py tests/test_arteta_agent_registry.py tests/test_arteta_agent_web_security.py`
  - Result: no matches.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.

### Risk Notes

- Python 3.8 is still not available in the local Windows launcher, so direct `python3.8 -m py_compile` could not be run here. The touched files were checked for Python 3.9+ annotation syntax and compiled under the available interpreter.
- The optional remote fetch proxy still depends on the remote service enforcing its own SSRF and egress policy; local validation prevents this code path from knowingly forwarding unsafe URLs from this agent.

### Remaining

- Decide whether a minimal `ToolResult.data` field is needed after all Web tools now return structured status/content/markers.
- Move search, X, and verification helpers out of `web_access.py` during Round 3 without changing behavior.

## 2026-07-12 Web Access Round 2 Remote Proxy Sensitive URL Guard

### Scope

- Closed the remaining Round 2 remote fetch privacy boundary.
- Kept local fetch behavior unchanged.
- Did not introduce `ToolResult.data`; current Web consumers only require structured `status`, `content`, `markers`, `artifacts`, and `error_code`.

### Changes

- Added `_has_sensitive_remote_query()` for query keys containing credential-like terms such as `token`, `key`, `signature`, `auth`, `secret`, `password`, `session`, and related forms.
- `web_fetch()` no longer sends URLs with sensitive query keys to the optional Grok remote fetch proxy, even when `ARTETA_ALLOW_REMOTE_FETCH_PROXY=1`.
- `fetch_x_post()` no longer sends URLs with sensitive query keys to the configured X Fetch Bridge.
- X public syndication and mirror fallback may still run because they use the tweet id/path rather than forwarding the full sensitive query URL to a remote proxy.

### RED Checks Before Implementation

- `test_web_fetch_does_not_send_sensitive_query_to_remote_proxy` failed because `web_fetch()` still validated and forwarded a URL containing `access_token` to the remote fetch proxy path.
- `test_fetch_x_post_skips_x_bridge_for_sensitive_query` failed because `fetch_x_post()` still sent a URL containing `auth` to the X Fetch Bridge.

### Verification

- `python -m pytest tests/test_arteta_agent_tool_result_protocol.py -q`
  - RED result before implementation: `2 failed, 9 passed`.
  - GREEN result after implementation: `11 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py tests/test_arteta_agent_web_security.py tests/test_arteta_agent_web_verification.py -q`
  - Result: `204 passed`.
- `python -m pytest tests -q`
  - Result: `582 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "\b(dict|list|set|tuple)\[|\|\s*None|None\s*\|" plugins/arteta_agent/tools/web_access.py tests/test_arteta_agent_tool_result_protocol.py`
  - Result: no matches.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.

### Risk Notes

- The sensitive-query detector is conservative and can skip remote proxy assistance for benign query keys ending in credential-like words. This is intentional; remote proxy use is optional and local fetch remains the primary path.
- Remote services still need their own URL validation and network egress restrictions.

### Remaining

- Round 2 is functionally closed for current scope: Web tools return structured results, factual verification has conservative verdicts, remote proxy default/SSRF/sensitive-query boundaries are covered.
- Round 3 remains: split `web_access.py` into focused modules and add search backend abstractions without changing public tool behavior.

## 2026-07-12 Web Access Round 3 Compatibility Package Boundary

### Scope

- Started Round 3 with a mechanical package boundary move.
- Moved the existing Web implementation from `plugins/arteta_agent/tools/web_access.py` to `plugins/arteta_agent/tools/web/handlers.py`.
- Kept `plugins/arteta_agent/tools/web_access.py` as a compatibility alias so old imports and monkeypatch paths continue to reference the implementation module.

### Changes

- Added `plugins/arteta_agent/tools/web/__init__.py`.
- Added `plugins/arteta_agent/tools/web_access.py` compatibility shim:
  - imports `plugins.arteta_agent.tools.web.handlers`;
  - replaces `sys.modules[__name__]` with the handlers module.
- Updated relative imports in `handlers.py` for the deeper package level.
- Fixed the moved Grok snapshot helper to import `tools.link_analysis` from the parent package.
- Updated the provider shared-client source inspection test to inspect `tools/web/handlers.py`, where the HTTP implementation now lives.

### RED Checks Before Implementation

- `test_web_access_compatibility_module_delegates_to_web_handlers` failed because `plugins.arteta_agent.tools.web` did not exist yet.
- After the move, the Web/registry group exposed one path regression: `_write_grok_snapshot_image()` still used `from . import link_analysis`, which pointed at `tools.web.link_analysis`; this was corrected to `from .. import link_analysis`.

### Verification

- `python -m pytest tests/test_arteta_agent_web_modules.py -q`
  - RED result before implementation: `1 failed`.
  - GREEN result after implementation: `1 passed`.
- `python -m pytest tests/test_arteta_agent_tool_result_protocol.py tests/test_arteta_agent_registry.py tests/test_arteta_agent_web_security.py tests/test_arteta_agent_web_verification.py tests/test_arteta_agent_web_modules.py -q`
  - First result after move: `1 failed, 215 passed`.
  - Final result after import fix: `216 passed`.
- `python -m pytest tests/test_arteta_agent_provider.py tests/test_arteta_agent_web_modules.py tests/test_arteta_agent_registry.py -q`
  - Result: `209 passed`.
- `python -m pytest tests -q`
  - Result: `583 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "\b(dict|list|set|tuple)\[|\|\s*None|None\s*\|" plugins/arteta_agent/tools/web_access.py plugins/arteta_agent/tools/web tests/test_arteta_agent_web_modules.py tests/test_arteta_agent_provider.py`
  - Result: no matches.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.

### Risk Notes

- This commit intentionally moves implementation without changing behavior. It creates the package boundary needed for later extraction but does not yet separate security, parsing, search backends, X reading, and verification into individual modules.
- The `sys.modules` compatibility alias preserves old monkeypatch behavior but should remain a transitional adapter; future imports inside new code should prefer `plugins.arteta_agent.tools.web.handlers` or the specific extracted modules.

### Remaining

- Extract security/fetch helpers into focused modules.
- Introduce `SearchBackend` abstraction and typed internal search hit models.
- Extract X reader and verification helpers while keeping public tool names unchanged.

## 2026-07-12 Web Access Round 3 Security Module Extraction

### Scope

- Extracted URL, SSRF, content-type, content-length, and sensitive-query helpers from `tools/web/handlers.py` to `tools/web/security.py`.
- Preserved compatibility by importing the same private helper names back into `handlers.py`, so legacy access through `plugins.arteta_agent.tools.web_access._safe_url` still works.
- Did not change public tool behavior or schema.

### Changes

- Added `plugins/arteta_agent/tools/web/security.py` with:
  - `_ValidatedURL`;
  - URL syntax and netloc validation;
  - DNS-aware public IP validation;
  - sensitive remote query detection;
  - text Content-Type and Content-Length helpers;
  - fetch URL constants.
- Removed duplicate helper implementations from `handlers.py`.
- Extended `tests/test_arteta_agent_web_modules.py` to assert compatibility exports still point at the extracted security helpers.

### RED Checks Before Implementation

- `test_web_security_helpers_are_extracted_but_compatibly_exported` failed because `plugins.arteta_agent.tools.web.security` did not exist.

### Verification

- `python -m pytest tests/test_arteta_agent_web_modules.py tests/test_arteta_agent_web_security.py tests/test_arteta_agent_tool_result_protocol.py -q`
  - Result: `20 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py tests/test_arteta_agent_provider.py tests/test_arteta_agent_web_verification.py tests/test_arteta_agent_web_modules.py -q`
  - Result: `215 passed`.
- `python -m pytest tests -q`
  - Result: `584 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "\b(dict|list|set|tuple)\[|\|\s*None|None\s*\|" plugins/arteta_agent/tools/web tests/test_arteta_agent_web_modules.py tests/test_arteta_agent_provider.py`
  - Result: no matches.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.

### Risk Notes

- The extracted module keeps underscore-prefixed names because current tests and compatibility callers still use the old private helper names through `web_access`.
- Stronger connection-layer SSRF protection such as IP pinning remains outside this application-layer extraction.

### Remaining

- Extract fetch/page parsing and formatting helpers.
- Introduce `SearchBackend` abstraction and typed internal search hit models.
- Extract X reader and verification helpers while keeping public tool names unchanged.

## 2026-07-12 Web Access Round 3 Search Backend Abstraction

### Scope

- Added internal structured search models and a minimal `SearchBackend` abstraction.
- Routed `_search_web()` through the backend abstraction while preserving the old public return shape (`list[dict]`) for existing formatters and tests.
- Kept the existing Grok-first, legacy fallback behavior.

### Changes

- Added `plugins/arteta_agent/tools/web/models.py`:
  - `SearchHit` dataclass;
  - `from_mapping()` compatibility adapter for legacy dict search results;
  - `to_legacy_dict()` adapter for existing formatters.
- Added `plugins/arteta_agent/tools/web/search_backends.py`:
  - `SearchBackend` protocol;
  - `CallableSearchBackend` adapter for current search functions;
  - `run_search_backends()` sequential runner.
- Added `_search_backends_for_request()` in `handlers.py`:
  - wraps `_groksearch_search()` when GrokSearch is configured;
  - always appends the legacy `_duckduckgo_search()` fallback;
  - keeps Grok errors non-fatal and keeps the final backend error/timeout behavior visible to callers.
- Updated module tests to prove `_search_web()` can run through a fake backend and still return the legacy dict shape.

### RED Checks Before Implementation

- `test_search_web_uses_search_backend_abstraction` failed because `plugins.arteta_agent.tools.web.models` did not exist.

### Verification

- `python -m pytest tests/test_arteta_agent_web_modules.py -q`
  - RED result before implementation: `1 failed, 2 passed`.
  - GREEN result after implementation: `3 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py tests/test_arteta_agent_web_verification.py tests/test_arteta_agent_web_security.py tests/test_arteta_agent_tool_result_protocol.py -q`
  - Result: `215 passed`.
- `python -m pytest tests -q`
  - Result: `585 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "\b(dict|list|set|tuple)\[|\|\s*None|None\s*\|" plugins/arteta_agent/tools/web tests/test_arteta_agent_web_modules.py`
  - Result: no matches.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.

### Risk Notes

- Search parsers still return legacy dictionaries internally; `SearchHit.from_mapping()` is the compatibility bridge.
- More granular backend classes (`GrokSearchBackend`, `BingHtmlBackend`, etc.) remain future extraction work, but the execution path now has a real backend interface and runner.

### Remaining

- Extract fetch/page parsing and formatting helpers.
- Extract X reader and verification helpers while keeping public tool names unchanged.

## 2026-07-12 Web Access Round 3 X Reader Extraction

### Scope

- Extracted pure X/Twitter URL parsing and formatting helpers from `handlers.py` to `x_reader.py`.
- Kept network channel functions in `handlers.py` so existing tests and monkeypatch paths for `_fetch_x_syndication`, `_fetch_x_mirror`, and `_x_fetch_bridge_fetch` remain compatible.
- Public tool name `fetch_x_post` and its behavior are unchanged.

### Changes

- Added `plugins/arteta_agent/tools/web/x_reader.py` with:
  - `MetaExtractor`;
  - `_x_status_id`, `_x_username`, `_is_x_status_url`;
  - `_extract_x_text`, `_extract_x_author`;
  - `_x_mirror_urls`;
  - `_format_x_mirror_page`, `_format_x_post`.
- Imported these helpers back into `handlers.py`, preserving old private helper access through `web_access`.
- Extended module tests to assert compatibility exports point at `x_reader.py`.

### RED Checks Before Implementation

- `test_x_reader_helpers_are_extracted_but_compatibly_exported` failed because `plugins.arteta_agent.tools.web.x_reader` did not exist.
- Initial extraction removed `_fetch_x_mirror` too broadly; targeted X tests caught the missing monkeypatch-compatible network function, and it was restored in `handlers.py`.

### Verification

- `python -m pytest tests/test_arteta_agent_web_modules.py tests/test_arteta_agent_registry.py::test_fetch_x_post_reads_public_syndication_payload tests/test_arteta_agent_registry.py::test_fetch_x_post_prefers_authenticated_x_bridge tests/test_arteta_agent_registry.py::test_fetch_x_post_reads_public_mirror_metadata tests/test_arteta_agent_registry.py::test_fetch_x_post_rejects_mirror_metadata_for_different_author tests/test_arteta_agent_tool_result_protocol.py::test_fetch_x_post_returns_structured_tool_result tests/test_arteta_agent_tool_result_protocol.py::test_fetch_x_post_skips_x_bridge_for_sensitive_query -q`
  - First result after extraction: `2 failed, 8 passed`.
  - Final result after restoring `_fetch_x_mirror`: `10 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py tests/test_arteta_agent_web_security.py tests/test_arteta_agent_web_verification.py tests/test_arteta_agent_tool_result_protocol.py tests/test_arteta_agent_web_modules.py -q`
  - Result: `219 passed`.
- `python -m pytest tests -q`
  - Result: `586 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "\b(dict|list|set|tuple)\[|\|\s*None|None\s*\|" plugins/arteta_agent/tools/web tests/test_arteta_agent_web_modules.py`
  - Result: no matches.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.

### Risk Notes

- `x_reader.py` currently owns pure parsing/formatting only. Network provenance (`configured_bridge`, public syndication, third-party mirror, Grok extraction) is still represented by the handler control flow rather than a dedicated provenance model.

### Remaining

- Extract fetch/page parsing and formatting helpers.
- Extract verification helpers while keeping public tool names unchanged.

## 2026-07-12 Web Access Round 3 Verification Helper Extraction

### Scope

- Extracted source ranking and conservative claim-verification helper logic from `handlers.py` to `verification.py`.
- Kept public tool name `verify_recent_claim` and monkeypatch-compatible handler flow in `handlers.py`.
- Preserved private compatibility exports through `plugins.arteta_agent.tools.web_access`.

### Changes

- Added `plugins/arteta_agent/tools/web/verification.py` with:
  - `_VerificationEvidence`;
  - primary and authoritative media domain lists;
  - domain/source-level helpers;
  - claim-result scoring helpers;
  - stance classification and verdict formatting helpers.
- Imported extracted helpers back into `handlers.py` so legacy private imports continue to work.
- Restored shared handler-local helpers `_safe_int` and `_safe_float`.
- Re-exported `_clean_text` from `verification.py` through `handlers.py` because `link_analysis.py` still calls `web_access._clean_text`.
- Restored `PageExtractor` in `handlers.py`; it belongs to page parsing, not verification, and `_parse_page()` still depends on it.
- Added module tests that assert extracted verification helpers remain compatibly exported.

### RED Checks Before Implementation

- `test_verification_helpers_are_extracted_but_compatibly_exported` failed because `plugins.arteta_agent.tools.web.verification` did not exist.
- After the first mechanical extraction, targeted tests failed with:
  - `NameError: _safe_int is not defined`;
  - `NameError: _clean_text is not defined`.
- After restoring those helpers, verification behavior tests failed because `PageExtractor` had also been removed and `_parse_page()` fell back to search snippets. Restoring `PageExtractor` fixed the actual parsing regression.

### Verification

- `python -m pytest tests/test_arteta_agent_web_modules.py tests/test_arteta_agent_web_verification.py tests/test_arteta_agent_web_security.py::test_claim_ranking_has_no_task_specific_entity_hardcodes tests/test_arteta_agent_registry.py::test_web_source_level_requires_exact_or_subdomain_primary_match -q`
  - Initial result after mechanical extraction: `6 failed, 6 passed`.
  - Intermediate result after helper restoration: `4 failed, 8 passed`.
  - Final result: `12 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py tests/test_arteta_agent_web_security.py tests/test_arteta_agent_web_verification.py tests/test_arteta_agent_tool_result_protocol.py tests/test_arteta_agent_web_modules.py -q`
  - Result: `220 passed`.
- `python -m pytest tests -q`
  - Result: `587 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "\b(dict|list|set|tuple)\[|\|\s*None|None\s*\|" plugins/arteta_agent/tools/web tests/test_arteta_agent_web_modules.py`
  - Result: no matches.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.

### Risk Notes

- `verification.py` still exposes underscore-prefixed helper names intentionally; this keeps existing tests and compatibility imports stable while behavior is unchanged.
- `PageExtractor` remains in `handlers.py` for now. It should move with fetch/page parsing in a later mechanical extraction.
- Verification remains conservative and heuristic-based; a full evidence/stance subsystem is still a separate project.

### Remaining

- Extract fetch/page parsing and formatting helpers.
- Consider splitting individual search parsers/backends after behavior remains stable.

## 2026-07-12 Web Access Round 3 Fetch/Page Extraction

### Scope

- Extracted page parsing, page evidence formatting, limited response reading, and the underlying HTTP fetch implementation from `handlers.py` to `fetch.py`.
- Kept the public/private compatibility surface under `plugins.arteta_agent.tools.web_access`.
- Preserved the existing `_fetch_url` monkeypatch contract by keeping a thin wrapper in `handlers.py` that passes the handler-local `_http_client` dependency into `fetch._fetch_url`.

### Changes

- Added `plugins/arteta_agent/tools/web/fetch.py` with:
  - `PageExtractor`;
  - `_parse_page`;
  - `_format_page_evidence`;
  - `_fetch_url`;
  - `_read_limited_response`.
- Imported page parsing and formatting helpers back into `handlers.py`.
- Added `_fetch_url_impl` import and retained handler-level `_fetch_url` as a compatibility wrapper.
- Removed the old page parsing/fetch bodies from `handlers.py`.
- Added module tests proving helpers are extracted while the handler fetch wrapper still points at `fetch._fetch_url`.

### RED Checks Before Implementation

- `test_fetch_helpers_are_extracted_with_compatible_fetch_wrapper` failed because `plugins.arteta_agent.tools.web.fetch` did not exist.

### Verification

- `python -m pytest tests/test_arteta_agent_web_modules.py::test_fetch_helpers_are_extracted_with_compatible_fetch_wrapper -q`
  - RED result: `1 failed`.
  - GREEN result: `1 passed`.
- `python -m pytest tests/test_arteta_agent_web_modules.py tests/test_arteta_agent_web_security.py tests/test_arteta_agent_registry.py::test_web_fetch_extracts_citable_page_metadata tests/test_arteta_agent_registry.py::test_web_fetch_uses_groksearch_when_remote_proxy_enabled_and_local_fetch_fails tests/test_arteta_agent_registry.py::test_fetch_url_rechecks_final_redirect_url tests/test_arteta_agent_registry.py::test_fetch_url_stops_streaming_at_byte_limit tests/test_arteta_agent_registry.py::test_fetch_binary_rechecks_final_redirect_url tests/test_arteta_agent_tool_result_protocol.py::test_web_fetch_returns_structured_tool_result tests/test_arteta_agent_tool_result_protocol.py::test_web_fetch_does_not_use_remote_grok_proxy_by_default -q`
  - Result: `20 passed`.
- `python -m pytest tests/test_arteta_agent_registry.py tests/test_arteta_agent_web_security.py tests/test_arteta_agent_web_verification.py tests/test_arteta_agent_tool_result_protocol.py tests/test_arteta_agent_web_modules.py -q`
  - Result: `221 passed`.
- `python -m pytest tests -q`
  - Result: `588 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "\b(dict|list|set|tuple)\[|\|\s*None|None\s*\|" plugins/arteta_agent/tools/web tests/test_arteta_agent_web_modules.py`
  - Result: no matches.
- `python3.8 -m py_compile plugins/arteta_agent/tools/web/fetch.py plugins/arteta_agent/tools/web/handlers.py`
  - Result: not run; `python3.8` command is not installed on this workstation.
- `py -3.8 -m py_compile plugins/arteta_agent/tools/web/fetch.py plugins/arteta_agent/tools/web/handlers.py`
  - Result: not run; Windows launcher reports Python 3.8 is not installed.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.

### Risk Notes

- The handler-level `_fetch_url` wrapper is intentional. Existing tests and callers patch `web_access._http_client`; importing `fetch._fetch_url` directly would silently break that dependency injection path.
- `fetch.py` duplicates the public user agent and default byte/excerpt limits used by the web tool. Values are unchanged; a later cleanup can centralize shared constants if needed.

### Remaining

- Consider splitting individual search parsers/backends only if the next change needs it.
- Run deployment/smoke only after the web access package reaches a stable stop point or when explicitly requested.

## 2026-07-12 Web Access Round 3 Backend Budget And X Provenance

### Scope

- Completed the remaining Round 3 web backend cleanup without adding new public tools.
- Added an explicit shared search `TimeBudget` so backend fallback attempts consume one request-level budget.
- Added sanitized fallback logging for search and X-fetch backends.
- Added stable X provenance labels for configured bridge, public embed, mirror extraction, and Grok-generated extraction.

### Changes

- Added `TimeBudget` in `plugins/arteta_agent/tools/web/search_backends.py`.
- Updated `run_search_backends()` to pass the same budget object to each backend, cap per-backend timeout by remaining budget, and log backend failures with backend name plus exception class only.
- Kept existing monkeypatch-compatible fetch helper call shape in `_duckduckgo_search()` by enforcing remaining budget with outer `asyncio.wait_for()`.
- Kept legacy `_duckduckgo_search()` monkeypatch compatibility by falling back when a test replacement does not accept the new `budget` keyword.
- Added X provenance constants and formatting in `plugins/arteta_agent/tools/web/x_reader.py`.
- Removed the old duplicate X bridge backend line and stopped labeling Grok-generated X extraction as author `GrokSearch`.

### RED Checks Before Implementation

- `test_search_backends_share_explicit_time_budget` failed because `TimeBudget` did not exist and backend calls did not receive a shared budget.
- `test_search_backend_failure_logs_are_sanitized` failed because backend failures were silent.
- `test_fetch_x_post_reports_stable_provenance` failed because bridge output did not expose stable provenance.
- `test_grok_x_fallback_is_generated_extraction_not_fake_author` failed because Grok fallback used `author_name="GrokSearch"` and had no generated-extraction provenance.

### Verification

- `python -m pytest tests/test_arteta_agent_web_modules.py::test_search_backends_share_explicit_time_budget tests/test_arteta_agent_web_modules.py::test_search_backend_failure_logs_are_sanitized tests/test_arteta_agent_web_modules.py::test_fetch_x_post_reports_stable_provenance tests/test_arteta_agent_web_modules.py::test_grok_x_fallback_is_generated_extraction_not_fake_author -q`
  - RED result: `4 failed`.
  - GREEN result: `4 passed`.
- `python -m pytest tests/test_arteta_agent_web_modules.py tests/test_arteta_agent_web_security.py tests/test_arteta_agent_web_verification.py tests/test_arteta_agent_tool_result_protocol.py tests/test_arteta_agent_registry.py -q`
  - Initial result after budget/provenance changes: `5 failed, 220 passed`.
  - Cause: internal fetch helper calls passed the new `timeout_seconds` keyword to old two-argument monkeypatch replacements, and legacy `_duckduckgo_search` replacements did not accept `budget`.
  - Final result: `225 passed`.
- `python -m pytest tests -q`
  - Result: `592 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "\b(dict|list|set|tuple)\[|\|\s*None|None\s*\|" plugins/arteta_agent/tools/web tests/test_arteta_agent_web_modules.py`
  - Result: no matches.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.
- `python3.8 -m py_compile plugins/arteta_agent/tools/web_access.py plugins/arteta_agent/tools/web/*.py`
  - Result: not run; `python3.8` is not installed on this workstation.
- `py -3.8 -m py_compile plugins/arteta_agent/tools/web_access.py plugins/arteta_agent/tools/web/*.py`
  - Result: not run; Windows launcher reports Python 3.8 is not installed. Available launchers were Python 3.13 and 3.10.

### Risk Notes

- Search backend failure logs intentionally do not include the query, URL, token-bearing exception text, or response body.
- X provenance describes how evidence was obtained; `generated_extraction` remains a generated extraction, not an authenticated author/source identity.
- The `_duckduckgo_search()` compatibility fallback is limited to old replacements that reject the `budget` keyword. Real search calls still use the shared budget.

### Remaining

- ECS deployment and smoke test are still pending until deployment credentials or the manual target are available.
- No further Web Access features are included in this Round 3 cleanup commit.

## 2026-07-12 Web Access Round 3 Search Parser Extraction

### Scope

- Continued Round 3 module splitting by moving pure search-result parsers out of `handlers.py`.
- Kept the public/private compatibility surface unchanged by importing the same underscore helper names back into `handlers.py`.
- Did not change search backend ordering, HTTP behavior, ToolResult structure, or registered tool names.

### Changes

- Added `plugins/arteta_agent/tools/web/parsers/` with:
  - `bing.py` for Bing redirect normalization and HTML parsing;
  - `duckduckgo.py` for DuckDuckGo redirect normalization and HTML parsing;
  - `markdown.py` for Jina/DuckDuckGo Markdown parsing;
  - `grok.py` for GrokSearch search/content/source response parsing.
- Removed the corresponding parser function bodies from `handlers.py`.
- Added module-boundary coverage proving `handlers.py` still compatibly exports the parser helpers.

### RED Checks Before Implementation

- `test_search_parsers_are_extracted_but_compatibly_exported` failed with `ModuleNotFoundError: No module named 'plugins.arteta_agent.tools.web.parsers'`.

### Verification

- `python -m pytest tests/test_arteta_agent_web_modules.py::test_search_parsers_are_extracted_but_compatibly_exported -q`
  - RED result: `1 failed`.
  - GREEN result: `1 passed`.
- `python -m pytest tests/test_arteta_agent_web_modules.py tests/test_arteta_agent_web_security.py tests/test_arteta_agent_web_verification.py tests/test_arteta_agent_tool_result_protocol.py tests/test_arteta_agent_registry.py -q`
  - Result: `226 passed`.
- `python -m pytest tests -q`
  - Result: `593 passed`.
- `python -m compileall -q plugins tests tools dashboard`
  - Result: passed.
- `rg -n "\b(dict|list|set|tuple)\[|\|\s*None|None\s*\|" plugins/arteta_agent/tools/web tests/test_arteta_agent_web_modules.py`
  - Result: no matches.
- `python tools\verify_features.py --suite agent_registry --suite agent_permissions`
  - Result: passed.

### Risk Notes

- Parser modules intentionally depend only on existing security and verification text helpers. Network calls and backend orchestration remain outside parser modules.
- Compatibility exports remain underscore-prefixed because existing tests and legacy monkeypatch paths still import these helpers through `web_access`/`handlers`.

### Remaining

- Continue Round 3 by extracting registration/formatting or concrete search backend classes from `handlers.py`.
- ECS deployment and smoke test are still pending until deployment credentials or the manual target are available.
