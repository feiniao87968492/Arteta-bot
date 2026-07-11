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
