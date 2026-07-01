import importlib
import unittest

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()


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

        self.assertIn(long_message[:20] + "…", block)
        self.assertIn("…", block)
        self.assertNotIn(long_message, block)

    def test_format_recent_group_context_returns_empty_for_no_rows(self):
        chat = importlib.import_module("plugins.arteta_chat")

        self.assertEqual("", chat.format_recent_group_context([]))

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

        content = messages[0]["content"]
        self.assertLess(content.index("【最近群聊上下文（由旧到新）】"), content.index("【相关历史对话（本群）】"))
        self.assertIn("你玩过三国杀吗", content)
        self.assertIn("那内奸和反贼是谁", content)


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


if __name__ == "__main__":
    unittest.main()
