# Help Menu Clear Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the new admin-only clear-memory command to the rendered help menu so the in-bot help output matches the actual command set.

**Architecture:** Update the single source of truth for help rendering in `plugins/arteta_help.py` by adding one concise line under the admin section. Verify the rendered help source text includes the command and keep the wording short to preserve the current layout and tone.

**Tech Stack:** Python 3.8, NoneBot2 plugin helpers, pytest/unittest, Markdown docs

---

## File Structure

- Modify: `plugins/arteta_help.py` — add the clear-memory admin command line to `build_help_text()`.
- Modify: `tests/test_arteta_help.py` — add a focused regression test asserting `build_help_text()` includes the clear-memory command wording.

---

### Task 1: Update help text and lock it with a regression test

**Files:**
- Modify: `plugins/arteta_help.py`
- Modify: `tests/test_arteta_help.py`

- [ ] **Step 1: Write the failing test**

Add or extend `tests/test_arteta_help.py` with a focused assertion on the help text content.

```python
from plugins.arteta_help import build_help_text


def test_build_help_text_includes_clear_memory_admin_command():
    text = build_help_text()

    assert "clear/清除记忆/清空记忆" in text
    assert "长期对话记忆" in text
    assert "仅管理员" in text or "教练组" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_arteta_help.py -q
```

Expected: FAIL because the current help text does not include the clear-memory command line yet.

- [ ] **Step 3: Write minimal implementation**

Update the admin section in `plugins/arteta_help.py` by adding one concise line that matches the approved short wording style.

```python
"clear/清除记忆/清空记忆：清空当前群的长期对话记忆（仅管理员）。\n"
```

Place it in the existing `"*--- 球队管理（仅限教练组）---*"` block near the other admin commands.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/test_arteta_help.py -q
```

Expected: PASS.

Then run a nearby regression check:

```bash
python -m pytest tests/test_arteta_help.py tests/test_arteta_tools.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/arteta_help.py tests/test_arteta_help.py
git commit -m "fix: add clear command to help menu"
```

---

## Self-Review

- **Spec coverage:** the plan updates the rendered help source and adds a regression test that locks the new command text in place.
- **Placeholder scan:** no TODO/TBD markers remain; each step has exact files, code, and commands.
- **Type consistency:** helper name remains `build_help_text`, matching the existing codebase and tests.
