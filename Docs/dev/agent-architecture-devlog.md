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
