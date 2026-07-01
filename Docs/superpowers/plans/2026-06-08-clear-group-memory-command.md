# Clear Group Memory Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin-only `clear` command that deletes only the current group's long-term ChromaDB conversation memory.

**Architecture:** Extend `MemoryStore` with a group-scoped delete method, then add a group-chat command handler in `plugins/arteta_chat.py` that validates context and permissions before invoking it. Verify behavior with focused tests for both the storage boundary and the command-facing control flow, then document the command and its scope.

**Tech Stack:** Python 3.8, NoneBot2, OneBot V11, ChromaDB, pytest/unittest, Markdown docs

---

## File Structure

- Modify: `plugins/arteta_memory.py` — add `clear_group_memories(group_id)` that deletes only matching `group_memories` documents and returns the deleted count.
- Modify: `plugins/arteta_chat.py` — register the new `clear` / `清除记忆` / `清空记忆` command and enforce group-only + admin-only access before clearing memory.
- Modify: `tests/test_arteta_memory.py` — add storage-layer regression tests proving only the target group is cleared.
- Modify: `tests/test_arteta_chat_commands.py` — add command-level tests for admin success, non-admin rejection, and private-chat rejection. If this file does not exist yet, create it as the focused home for command-behavior tests.
- Modify: `Docs/dev/chromadb-memory.md` — document the new admin clear command and its scope.
- Modify: `Docs/user/commands.md` — document the new command as admin-only and group-only.

---

### Task 1: Add storage-layer delete capability

**Files:**
- Modify: `plugins/arteta_memory.py`
- Modify: `tests/test_arteta_memory.py`

- [ ] **Step 1: Write the failing test for group-scoped deletion**

Add tests to `tests/test_arteta_memory.py` that exercise `MemoryStore.clear_group_memories()` directly. Use a fake collection so the test does not need a real ChromaDB process.

```python
class FakeMemoryCollection(object):
    def __init__(self):
        self.rows = []

    def add(self, documents, metadatas, ids):
        for document, metadata, item_id in zip(documents, metadatas, ids):
            self.rows.append({
                "id": item_id,
                "document": document,
                "metadata": metadata,
            })

    def query(self, query_texts=None, n_results=5, where=None):
        group_id = str((where or {}).get("group_id", ""))
        matches = [row for row in self.rows if str(row["metadata"].get("group_id")) == group_id]
        matches = matches[:n_results]
        return {
            "documents": [[row["document"] for row in matches]],
            "metadatas": [[row["metadata"] for row in matches]],
            "ids": [[row["id"] for row in matches]],
        }

    def get(self, where=None, include=None):
        group_id = str((where or {}).get("group_id", ""))
        matches = [row for row in self.rows if str(row["metadata"].get("group_id")) == group_id]
        return {
            "ids": [row["id"] for row in matches],
        }

    def delete(self, ids=None):
        ids = set(ids or [])
        self.rows = [row for row in self.rows if row["id"] not in ids]


def test_clear_group_memories_only_deletes_target_group():
    store = memory_module.MemoryStore()
    store.collection = FakeMemoryCollection()
    store._ready = True

    store.add_memory("100", "u1", "hello", "reply", nickname="A", aliases=[])
    store.add_memory("200", "u2", "world", "reply", nickname="B", aliases=[])

    deleted = store.clear_group_memories("100")

    assert deleted == 1
    assert store.query_memories("100", "hello") == []
    assert len(store.query_memories("200", "world")) == 1


def test_clear_group_memories_returns_zero_when_store_not_ready():
    store = memory_module.MemoryStore()
    store._ready = False

    deleted = store.clear_group_memories("100")

    assert deleted == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/test_arteta_memory.py -q
```

Expected: FAIL with an `AttributeError` or equivalent because `MemoryStore.clear_group_memories` does not exist yet.

- [ ] **Step 3: Write the minimal implementation in `plugins/arteta_memory.py`**

Add a delete method that returns the number of removed records and only touches the current group.

```python
def clear_group_memories(self, group_id: str) -> int:
    """清除指定群的长期对话记忆，返回删除条数"""
    if not self._ready:
        return 0

    try:
        existing = self.collection.get(
            where={"group_id": str(group_id)},
            include=[],
        )
        ids = list(existing.get("ids") or [])
        if not ids:
            return 0
        self.collection.delete(ids=ids)
        return len(ids)
    except Exception as e:
        logger.warning(f"[MemoryStore] clear_group_memories 失败: {e}")
        return 0
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
python -m pytest tests/test_arteta_memory.py -q
```

Expected: PASS, including the new deletion tests.

- [ ] **Step 5: Commit**

```bash
git add plugins/arteta_memory.py tests/test_arteta_memory.py
git commit -m "feat: add group memory clear support"
```

---

### Task 2: Add the admin-only group command

**Files:**
- Modify: `plugins/arteta_chat.py`
- Modify: `tests/test_arteta_chat_commands.py`

- [ ] **Step 1: Write the failing command tests**

If `tests/test_arteta_chat_commands.py` does not exist, create it. Add focused tests for the permission and context rules using a small extracted helper from `arteta_chat.py` rather than trying to boot full NoneBot matcher state.

Planned helper API in production code:

```python
def can_clear_group_memory(event, user_id: str, admin_qq: str) -> Tuple[bool, str]:
    ...
```

Add tests like:

```python
import types

from plugins import arteta_chat


def test_can_clear_group_memory_allows_admin_in_group():
    event = types.SimpleNamespace(group_id=123)

    allowed, reason = arteta_chat.can_clear_group_memory(event, "2648955710", "2648955710")

    assert allowed is True
    assert reason == ""


def test_can_clear_group_memory_rejects_non_admin():
    event = types.SimpleNamespace(group_id=123)

    allowed, reason = arteta_chat.can_clear_group_memory(event, "111", "2648955710")

    assert allowed is False
    assert "管理员" in reason


def test_can_clear_group_memory_rejects_private_chat():
    event = types.SimpleNamespace()

    allowed, reason = arteta_chat.can_clear_group_memory(event, "2648955710", "2648955710")

    assert allowed is False
    assert "群聊" in reason
```

Also add a direct handler-facing test for the clear call orchestration:

```python
def test_handle_clear_group_memory_uses_current_group(monkeypatch):
    calls = []

    def fake_clear(group_id):
        calls.append(group_id)
        return 3

    monkeypatch.setattr(arteta_chat.memory_store, "clear_group_memories", fake_clear)

    message = arteta_chat.build_clear_group_memory_message("543915926")

    assert "3 条" in message
```

If you prefer, make the second helper explicit in production code:

```python
def clear_group_memory_for_event(group_id: str) -> str:
    ...
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
python -m pytest tests/test_arteta_chat_commands.py -q
```

Expected: FAIL because the new helper(s) and command behavior do not exist yet.

- [ ] **Step 3: Write the minimal implementation in `plugins/arteta_chat.py`**

1. Add a matcher near the existing command declarations:

```python
clear_memory_cmd = on_command("clear", aliases={"清除记忆", "清空记忆"}, priority=4, block=True)
```

2. Add small helpers to keep the command testable without booting the full matcher machinery:

```python
def can_clear_group_memory(event, user_id: str, admin_qq: str) -> Tuple[bool, str]:
    if not isinstance(event, GroupMessageEvent):
        return False, "该命令仅限群聊使用。"
    if str(user_id) != str(admin_qq):
        return False, "只有管理员才能清除本群长期记忆。"
    return True, ""


def build_clear_group_memory_message(deleted_count: int) -> str:
    if deleted_count <= 0:
        return "本群当前没有可清除的长期对话记忆。"
    return "已清除本群 %d 条长期对话记忆。" % deleted_count
```

3. Add the handler:

```python
@clear_memory_cmd.handle()
async def handle_clear_memory(event: MessageEvent):
    user_id = event.get_user_id()
    allowed, reason = can_clear_group_memory(event, user_id, ADMIN_QQ)
    if not allowed:
        await clear_memory_cmd.finish(reason)

    group_id = str(event.group_id)
    deleted_count = memory_store.clear_group_memories(group_id)
    await clear_memory_cmd.finish(build_clear_group_memory_message(deleted_count))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
python -m pytest tests/test_arteta_chat_commands.py -q
```

Expected: PASS.

Then run the memory tests again to ensure no regression:

```bash
python -m pytest tests/test_arteta_memory.py tests/test_arteta_chat_commands.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/arteta_chat.py tests/test_arteta_chat_commands.py
git commit -m "feat: add clear group memory command"
```

---

### Task 3: Document the command and memory boundary

**Files:**
- Modify: `Docs/dev/chromadb-memory.md`
- Modify: `Docs/user/commands.md`
- Optional Modify: `Docs/dev/overview.md`

- [ ] **Step 1: Write the failing docs expectation as a checklist note**

Create a small local checklist in your working notes before editing:

```text
- developer doc mentions admin clear command
- user commands doc lists clear / 清除记忆 / 清空记忆
- docs state it clears only current group ChromaDB memory
- docs state it does not affect football_news or SQLite tables
```

This is the “test first” equivalent for doc scope: the docs are incomplete until all four expectations are satisfied.

- [ ] **Step 2: Update `Docs/dev/chromadb-memory.md`**

Add a short section describing the new admin command and its exact scope. Include wording like:

```markdown
### 管理员清理入口

当前支持管理员在群聊中使用 `clear`（别名：`清除记忆`、`清空记忆`）立即清空本群的长期对话记忆。

- 只影响 ChromaDB `group_memories` collection 中 `group_id=当前群号` 的记录
- 不影响 SQLite 中的 `players`、`messages`、`nicknames` 等结构化数据
- 不影响 `football_news` 新闻向量库
```

- [ ] **Step 3: Update `Docs/user/commands.md`**

Add a command row or bullet like:

```markdown
- `clear` / `清除记忆` / `清空记忆` — **仅管理员**可用，清空当前群的长期对话记忆（只清 ChromaDB 群记忆，不删档案/好感度/新闻库）
```

- [ ] **Step 4: Run a quick verification pass on the changed docs**

Run:

```bash
python - <<'PY'
from pathlib import Path
paths = [
    Path('Docs/dev/chromadb-memory.md'),
    Path('Docs/user/commands.md'),
]
for path in paths:
    text = path.read_text(encoding='utf-8')
    print(path)
    for needle in ['clear', '清除记忆', '当前群', 'football_news']:
        print(' ', needle, needle in text)
PY
```

Expected: every required keyword prints `True` in the appropriate document set.

- [ ] **Step 5: Commit**

```bash
git add Docs/dev/chromadb-memory.md Docs/user/commands.md
git commit -m "docs: add clear memory command docs"
```

---

### Task 4: Full targeted verification

**Files:**
- Modify: none
- Test: `tests/test_arteta_memory.py`
- Test: `tests/test_arteta_chat_commands.py`
- Test: `tools/verify_features.py` (existing runner only)

- [ ] **Step 1: Run the focused automated tests**

Run:

```bash
python -m pytest tests/test_arteta_memory.py tests/test_arteta_chat_commands.py tests/test_arteta_tools.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the chat verification suite**

Run:

```bash
python tools/verify_features.py --suite chat
```

Expected: PASS, or `skipped` only for cases already documented as environment-dependent. No new failure should be introduced by the clear command.

- [ ] **Step 3: Inspect verification artifacts if the suite fails**

If the suite fails, inspect the generated report before changing code again:

```bash
python - <<'PY'
from pathlib import Path
root = Path('artifacts/verify')
latest = max(root.iterdir(), key=lambda p: p.stat().st_mtime)
print(latest)
print((latest / 'summary.txt').read_text(encoding='utf-8', errors='ignore'))
PY
```

Expected: either a clean summary or a concrete failure location to debug.

- [ ] **Step 4: Sanity-check the new command path manually in code terms**

Before finishing, confirm the three invariants by reading the changed code:

```text
1. command aliases include clear / 清除记忆 / 清空记忆
2. non-group or non-admin path returns early
3. only memory_store.clear_group_memories(group_id) is called
```

- [ ] **Step 5: Final commit**

```bash
git add plugins/arteta_memory.py plugins/arteta_chat.py tests/test_arteta_memory.py tests/test_arteta_chat_commands.py Docs/dev/chromadb-memory.md Docs/user/commands.md
git commit -m "feat: add clear command for group memories"
```

---

## Self-Review

- **Spec coverage:**
  - user-facing command naming and scope → Task 2, Task 3
  - group-only + admin-only restrictions → Task 2
  - ChromaDB-only deletion boundary → Task 1, Task 3
  - tests for storage + command control flow → Task 1, Task 2, Task 4
  - deployment/docs clarity → Task 3
- **Placeholder scan:** no TODO/TBD markers remain; each code change step includes concrete code and commands.
- **Type consistency:** helper names are consistent across tasks: `clear_group_memories`, `can_clear_group_memory`, `build_clear_group_memory_message`.
