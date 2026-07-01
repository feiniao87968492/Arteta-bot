# Recent Group Context Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inject the recent group chat timeline into Arteta chat prompts so short-range references like “那内奸和反贼是谁” correctly use the immediately preceding “你玩过三国杀吗” message.

**Architecture:** Add focused helper functions in `plugins/arteta_chat.py` that read recent messages from `daily_messages`, format them as a bounded chronological context block, and append that block to the system prompt before semantic ChromaDB memories. Keep ChromaDB group memories for long-range semantic recall; use the recent timeline for deterministic short-range context.

**Tech Stack:** Python 3.8, SQLite/aiosqlite, NoneBot2 OneBot V11, unittest, existing `tools/verify_features.py` chat suite patterns.

---

## File Structure

- Modify `plugins/arteta_chat.py`
  - Add constants for recent context bounds.
  - Add `get_recent_group_messages()` async SQLite helper.
  - Add `format_recent_group_context()` pure formatter.
  - Inject formatted recent group context in `process_chat()` after `messages = [{"role": "system", ...}]` and before alias/Chroma/football-news context.
- Modify `tests/test_arteta_memory.py` or create `tests/test_recent_group_context.py`
  - Prefer creating `tests/test_recent_group_context.py` so the new prompt-context behavior is isolated from ChromaDB memory tests.
  - Test formatter behavior without NoneBot runtime.
  - Test SQLite helper against an isolated temporary DB by monkeypatching `plugins.arteta_chat.DB_PATH`.
- Optional modify `Docs/dev/chromadb-memory.md`
  - Document the distinction between deterministic recent group context and semantic long-range ChromaDB memory.

---

### Task 1: Add pure formatting tests for recent group context

**Files:**
- Create: `tests/test_recent_group_context.py`
- Modify later: `plugins/arteta_chat.py`

- [ ] **Step 1: Create the test file with a failing formatter test**

Create `tests/test_recent_group_context.py` with this content:

```python
import importlib
import unittest


class RecentGroupContextFormatTests(unittest.TestCase):
    def test_format_recent_group_context_keeps_chronological_sanguosha_context(self):
        chat = importlib.import_module("plugins.arteta_chat")
        rows = [
            {
                "nickname": "【gooner】塔剩",
                "user_id": "2814399285",
                "message": "你玩过三国杀吗",
                "timestamp": 1779539817,
            },
            {
                "nickname": "头号塔卫兵董方卓",
                "user_id": "2648955710",
                "message": "那内奸和反贼是谁",
                "timestamp": 1779539913,
            },
        ]

        block = chat.format_recent_group_context(rows)

        self.assertIn("【最近群聊上下文（由旧到新）】", block)
        self.assertLess(block.index("你玩过三国杀吗"), block.index("那内奸和反贼是谁"))
        self.assertIn("【gooner】塔剩", block)
        self.assertIn("头号塔卫兵董方卓", block)
        self.assertIn("请优先用这段最近群聊上下文解析", block)

    def test_format_recent_group_context_truncates_long_messages(self):
        chat = importlib.import_module("plugins.arteta_chat")
        long_message = "阿森纳" * 120
        rows = [{
            "nickname": "长文球员",
            "user_id": "10001",
            "message": long_message,
            "timestamp": 1779539817,
        }]

        block = chat.format_recent_group_context(rows, max_message_chars=20)

        self.assertIn("阿森纳阿森纳阿森纳阿森纳阿森纳阿森纳阿森纳", block)
        self.assertIn("…", block)
        self.assertNotIn(long_message, block)

    def test_format_recent_group_context_returns_empty_for_no_rows(self):
        chat = importlib.import_module("plugins.arteta_chat")

        self.assertEqual("", chat.format_recent_group_context([]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the formatter tests and verify they fail**

Run:

```bash
python -m unittest tests.test_recent_group_context -v
```

Expected: FAIL with `AttributeError: module 'plugins.arteta_chat' has no attribute 'format_recent_group_context'`.

- [ ] **Step 3: Add minimal formatter implementation**

In `plugins/arteta_chat.py`, near the existing message/profile helper functions after `save_message()`, add:

```python
RECENT_GROUP_CONTEXT_LIMIT = 15
RECENT_GROUP_CONTEXT_MAX_MESSAGE_CHARS = 120


def _truncate_context_message(message: str, max_chars: int = RECENT_GROUP_CONTEXT_MAX_MESSAGE_CHARS) -> str:
    text = str(message or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def format_recent_group_context(rows: list, max_message_chars: int = RECENT_GROUP_CONTEXT_MAX_MESSAGE_CHARS) -> str:
    if not rows:
        return ""

    lines = [
        "【最近群聊上下文（由旧到新）】：",
    ]
    for row in rows:
        ts = datetime.fromtimestamp(int(row["timestamp"])).strftime("%m月%d日 %H:%M")
        nickname = str(row.get("nickname") or row.get("user_id") or "未知球员").strip()
        message = _truncate_context_message(str(row.get("message") or ""), max_message_chars)
        if not message:
            continue
        lines.append(f"- {ts} {nickname}：{message}")

    if len(lines) == 1:
        return ""

    lines.append("")
    lines.append("请优先用这段最近群聊上下文解析‘那/这个/他/谁/内奸/反贼’等短距离指代，再结合长期记忆回答。")
    return "\n".join(lines)
```

- [ ] **Step 4: Run formatter tests and verify they pass**

Run:

```bash
python -m unittest tests.test_recent_group_context -v
```

Expected: PASS.

---

### Task 2: Add SQLite helper tests for reading recent group messages

**Files:**
- Modify: `tests/test_recent_group_context.py`
- Modify later: `plugins/arteta_chat.py`

- [ ] **Step 1: Add failing async SQLite helper test**

Append this test class to `tests/test_recent_group_context.py` before the `if __name__ == "__main__"` block:

```python
class RecentGroupContextSQLiteTests(unittest.TestCase):
    def test_get_recent_group_messages_reads_current_group_in_chronological_order(self):
        import asyncio
        import os
        import sqlite3
        import tempfile

        chat = importlib.import_module("plugins.arteta_chat")
        old_db_path = chat.DB_PATH

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "recent_context.db")
            conn = sqlite3.connect(db_path)
            conn.execute("""CREATE TABLE daily_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                nickname TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL,
                timestamp INTEGER NOT NULL
            )""")
            conn.executemany(
                "INSERT INTO daily_messages (user_id, group_id, nickname, message, timestamp) VALUES (?, ?, ?, ?, ?)",
                [
                    ("old", "491603775", "旧消息", "这条太旧", 100),
                    ("2814399285", "491603775", "【gooner】塔剩", "你玩过三国杀吗", 200),
                    ("other", "123", "别群", "别群消息不能进来", 250),
                    ("2648955710", "491603775", "头号塔卫兵董方卓", "那内奸和反贼是谁", 300),
                ],
            )
            conn.commit()
            conn.close()

            try:
                chat.DB_PATH = db_path
                rows = asyncio.run(chat.get_recent_group_messages("491603775", limit=2))
            finally:
                chat.DB_PATH = old_db_path

        self.assertEqual(["你玩过三国杀吗", "那内奸和反贼是谁"], [row["message"] for row in rows])
        self.assertEqual(["2814399285", "2648955710"], [row["user_id"] for row in rows])
        self.assertNotIn("别群消息不能进来", [row["message"] for row in rows])
```

- [ ] **Step 2: Run the new SQLite helper test and verify it fails**

Run:

```bash
python -m unittest tests.test_recent_group_context.RecentGroupContextSQLiteTests -v
```

Expected: FAIL with `AttributeError: module 'plugins.arteta_chat' has no attribute 'get_recent_group_messages'`.

- [ ] **Step 3: Add minimal SQLite helper implementation**

In `plugins/arteta_chat.py`, directly after `format_recent_group_context()`, add:

```python
async def get_recent_group_messages(group_id: str, limit: int = RECENT_GROUP_CONTEXT_LIMIT) -> list:
    if not group_id or group_id == "private":
        return []

    safe_limit = max(1, min(int(limit or RECENT_GROUP_CONTEXT_LIMIT), 30))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT user_id, group_id, nickname, message, timestamp
            FROM daily_messages
            WHERE group_id = ? AND TRIM(message) != ''
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (str(group_id), safe_limit),
        ) as cursor:
            rows = await cursor.fetchall()

    items = [dict(row) for row in rows]
    items.reverse()
    return items
```

- [ ] **Step 4: Run SQLite helper tests and verify they pass**

Run:

```bash
python -m unittest tests.test_recent_group_context.RecentGroupContextSQLiteTests -v
```

Expected: PASS.

- [ ] **Step 5: Run all recent context tests**

Run:

```bash
python -m unittest tests.test_recent_group_context -v
```

Expected: PASS.

---

### Task 3: Inject recent group context into the chat prompt

**Files:**
- Modify: `plugins/arteta_chat.py:1418-1435`
- Test: `tests/test_recent_group_context.py`

- [ ] **Step 1: Add a pure prompt-composition helper test**

Append this test method to `RecentGroupContextFormatTests` in `tests/test_recent_group_context.py`:

```python
    def test_append_recent_group_context_adds_block_before_memory_context(self):
        chat = importlib.import_module("plugins.arteta_chat")
        messages = [{"role": "system", "content": "BASE"}]
        rows = [
            {
                "nickname": "【gooner】塔剩",
                "user_id": "2814399285",
                "message": "你玩过三国杀吗",
                "timestamp": 1779539817,
            },
            {
                "nickname": "头号塔卫兵董方卓",
                "user_id": "2648955710",
                "message": "那内奸和反贼是谁",
                "timestamp": 1779539913,
            },
        ]

        chat.append_recent_group_context(messages, rows)
        messages[0]["content"] += "\n\n【相关历史对话（本群）】：old memory"

        self.assertLess(
            messages[0]["content"].index("【最近群聊上下文（由旧到新）】"),
            messages[0]["content"].index("【相关历史对话（本群）】"),
        )
        self.assertIn("你玩过三国杀吗", messages[0]["content"])
        self.assertIn("那内奸和反贼是谁", messages[0]["content"])
```

- [ ] **Step 2: Run the prompt-composition test and verify it fails**

Run:

```bash
python -m unittest tests.test_recent_group_context.RecentGroupContextFormatTests.test_append_recent_group_context_adds_block_before_memory_context -v
```

Expected: FAIL with `AttributeError: module 'plugins.arteta_chat' has no attribute 'append_recent_group_context'`.

- [ ] **Step 3: Add prompt-composition helper**

In `plugins/arteta_chat.py`, directly after `get_recent_group_messages()`, add:

```python
def append_recent_group_context(messages: list, recent_rows: list) -> None:
    context_block = format_recent_group_context(recent_rows)
    if context_block:
        messages[0]["content"] += "\n\n" + context_block + "\n"
```

- [ ] **Step 4: Wire helper into `process_chat()`**

In `plugins/arteta_chat.py`, find this block:

```python
    messages = [{"role": "system", "content": base_prompt}]

    # 优先补充“某人今天说了什么”这类按别名追问的最近发言
    recent_alias_messages = find_recent_messages_by_alias(group_id, user_message)
```

Replace it with:

```python
    messages = [{"role": "system", "content": base_prompt}]

    recent_group_messages = await get_recent_group_messages(group_id, RECENT_GROUP_CONTEXT_LIMIT)
    append_recent_group_context(messages, recent_group_messages)

    # 优先补充“某人今天说了什么”这类按别名追问的最近发言
    recent_alias_messages = find_recent_messages_by_alias(group_id, user_message)
```

- [ ] **Step 5: Run recent context tests and verify they pass**

Run:

```bash
python -m unittest tests.test_recent_group_context -v
```

Expected: PASS.

- [ ] **Step 6: Run existing chat/memory-related tests**

Run:

```bash
python -m unittest tests.test_recent_group_context tests.test_arteta_memory -v
python tools/verify_features.py --suite chat
```

Expected: all pass. If `verify_features.py --suite chat` skips external dependencies, confirm there are no failures.

---

### Task 4: Document the recent context layer

**Files:**
- Modify: `Docs/dev/chromadb-memory.md`

- [ ] **Step 1: Add documentation section**

In `Docs/dev/chromadb-memory.md`, after section `4.3 别名追问补充链路`, add:

```markdown
### 4.4 最近群聊上下文窗口

ChromaDB 负责长期语义记忆，但不适合单独承担短距离指代解析。例如：

```text
塔剩：你玩过三国杀吗
董方卓：那内奸和反贼是谁
```

当前问题“那内奸和反贼是谁”必须看到上一条“你玩过三国杀吗”才能正确理解为三国杀身份。向量检索可能命中旧的“内鬼/反贼”类对话，不能保证命中最近相邻消息。

因此 `process_chat()` 会从 `daily_messages` 读取本群最近 15 条消息，按时间正序注入 system prompt：

```text
【最近群聊上下文（由旧到新）】：
- 05月23日 21:36 【gooner】塔剩：你玩过三国杀吗
- 05月23日 21:38 头号塔卫兵董方卓：那内奸和反贼是谁

请优先用这段最近群聊上下文解析‘那/这个/他/谁/内奸/反贼’等短距离指代，再结合长期记忆回答。
```

职责边界：

- 最近群聊上下文：解决当前群内连续聊天和短距离指代。
- ChromaDB `group_memories`：解决长期、跨天、语义相关的历史问答回忆。
- `find_recent_messages_by_alias()`：解决“某某刚才说了什么”这类按人追问。
```

- [ ] **Step 2: Run documentation-adjacent verification**

Run:

```bash
python -m unittest tests.test_recent_group_context -v
```

Expected: PASS. Documentation has no runtime test, but the code behavior documented above is covered by recent context tests.

---

### Task 5: Deploy to ECS and validate the reported scenario

**Files:**
- Upload: `plugins/arteta_chat.py`
- Upload: `Docs/dev/chromadb-memory.md`
- Upload: `tests/test_recent_group_context.py` if keeping tests on ECS

- [ ] **Step 1: Back up ECS files**

Run:

```bash
ssh arteta 'set -e; backup=/opt/arteta_bot/deploy_backups/recent_group_context_$(date +%Y%m%d_%H%M%S); mkdir -p "$backup"; for f in /opt/arteta_bot/plugins/arteta_chat.py /opt/arteta_bot/Docs/dev/chromadb-memory.md; do if [ -f "$f" ]; then cp "$f" "$backup/$(basename "$f")"; fi; done; echo "$backup"'
```

Expected: prints backup directory path.

- [ ] **Step 2: Upload changed files**

Run:

```bash
scp plugins/arteta_chat.py arteta:/opt/arteta_bot/plugins/arteta_chat.py
scp Docs/dev/chromadb-memory.md arteta:/opt/arteta_bot/Docs/dev/chromadb-memory.md
scp tests/test_recent_group_context.py arteta:/opt/arteta_bot/tests/test_recent_group_context.py
ssh arteta 'chown arteta:arteta /opt/arteta_bot/plugins/arteta_chat.py /opt/arteta_bot/Docs/dev/chromadb-memory.md /opt/arteta_bot/tests/test_recent_group_context.py'
```

Expected: all commands exit 0.

- [ ] **Step 3: Restart the bot**

Run:

```bash
ssh arteta 'supervisorctl restart arteta_bot && sleep 3 && supervisorctl status arteta_bot'
```

Expected: `arteta_bot RUNNING`.

- [ ] **Step 4: Verify plugin load and OneBot reconnect**

Run:

```bash
ssh arteta 'tail -n 80 /opt/arteta_bot/logs/arteta_bot.log'
```

Expected lines include:

```text
Succeeded to load plugin "arteta_chat"
Scheduler Started
Bot 3443862126 connected
```

- [ ] **Step 5: Verify prompt context helper against ECS data**

Run:

```bash
ssh arteta 'cat > /tmp/verify_recent_context.py <<'"'"'PY'"'"'
import sys
sys.path.insert(0, "/opt/arteta_bot")
import nonebot
nonebot.init()
from plugins.arteta_chat import get_recent_group_messages, format_recent_group_context
import asyncio
rows = asyncio.run(get_recent_group_messages("491603775", limit=15))
block = format_recent_group_context(rows)
print(block)
print("HAS_SANGUOSHA", "你玩过三国杀吗" in block)
print("HAS_TRAITOR", "那内奸和反贼是谁" in block)
PY
sudo -u arteta -H bash -lc 'cd /opt/arteta_bot && ENVIRONMENT=prod PYTHONPATH=/opt/arteta_bot /opt/arteta_bot/venv/bin/python /tmp/verify_recent_context.py'
rm -f /tmp/verify_recent_context.py'
```

Expected:

```text
HAS_SANGUOSHA True
HAS_TRAITOR True
```

If the group has many new messages and those two lines have fallen out of the latest 15, temporarily run the same script with `limit=30` only for verification. Do not change the production default without a separate design decision.

- [ ] **Step 6: Manual QQ validation**

In the target group, send two consecutive messages:

```text
你玩过三国杀吗
@米克尔.阿尔特塔 那内奸和反贼是谁
```

Expected: the bot treats “内奸/反贼” as 三国杀身份 context, not generic group “内鬼”.

---

## Self-Review

- Spec coverage: The plan implements deterministic recent group context, preserves ChromaDB long-range memory, keeps alias lookup unchanged, adds tests, docs, and ECS validation.
- Placeholder scan: No placeholder steps remain; all commands and expected outputs are explicit.
- Type consistency: `format_recent_group_context(rows, max_message_chars)`, `get_recent_group_messages(group_id, limit)`, and `append_recent_group_context(messages, recent_rows)` are consistently named and used.
