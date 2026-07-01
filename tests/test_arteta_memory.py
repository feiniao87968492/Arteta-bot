import importlib.util
import json
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "arteta_memory.py"
CHAT_MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "arteta_chat.py"


def load_arteta_memory_module():
    chromadb_stub = types.ModuleType("chromadb")
    chromadb_stub.PersistentClient = object

    chromadb_config_stub = types.ModuleType("chromadb.config")

    class FakeSettings(object):
        def __init__(self, anonymized_telemetry=False):
            self.anonymized_telemetry = anonymized_telemetry

    chromadb_config_stub.Settings = FakeSettings

    previous_chromadb = sys.modules.get("chromadb")
    previous_config = sys.modules.get("chromadb.config")
    sys.modules["chromadb"] = chromadb_stub
    sys.modules["chromadb.config"] = chromadb_config_stub
    try:
        spec = importlib.util.spec_from_file_location("arteta_memory_for_test", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous_chromadb is None:
            sys.modules.pop("chromadb", None)
        else:
            sys.modules["chromadb"] = previous_chromadb
        if previous_config is None:
            sys.modules.pop("chromadb.config", None)
        else:
            sys.modules["chromadb.config"] = previous_config


def install_chat_import_stubs(memory_module):
    previous = {}

    def remember(name, module):
        previous[name] = sys.modules.get(name)
        sys.modules[name] = module

    nonebot = types.ModuleType("nonebot")

    class DummyMatcher(object):
        def handle(self):
            def decorator(func):
                return func
            return decorator

    nonebot.on_command = lambda *args, **kwargs: DummyMatcher()
    nonebot.on_message = lambda *args, **kwargs: DummyMatcher()
    nonebot.on_notice = lambda *args, **kwargs: DummyMatcher()
    nonebot.require = lambda *args, **kwargs: None

    class DummyDriver(object):
        def __init__(self):
            self.config = types.SimpleNamespace(dict=lambda: {}, model_dump=lambda: {})

        def on_shutdown(self, func):
            return func

    nonebot.get_driver = lambda: DummyDriver()
    remember("nonebot", nonebot)

    nonebot_permission = types.ModuleType("nonebot.permission")
    nonebot_permission.SUPERUSER = object()
    remember("nonebot.permission", nonebot_permission)

    nonebot_params = types.ModuleType("nonebot.params")
    nonebot_params.CommandArg = object
    remember("nonebot.params", nonebot_params)

    nonebot_typing = types.ModuleType("nonebot.typing")
    nonebot_typing.T_State = dict
    remember("nonebot.typing", nonebot_typing)

    adapter = types.ModuleType("nonebot.adapters.onebot.v11")
    adapter.Bot = object
    adapter.Event = object
    adapter.Message = str
    adapter.MessageEvent = type("MessageEvent", (), {})
    adapter.GroupMessageEvent = type("GroupMessageEvent", (), {})
    adapter.NoticeEvent = type("NoticeEvent", (), {})
    adapter.MessageSegment = object
    adapter.GroupRecallNoticeEvent = type("GroupRecallNoticeEvent", (), {})
    remember("nonebot.adapters.onebot.v11", adapter)

    message_mod = types.ModuleType("nonebot.adapters.onebot.v11.message")
    message_mod.Message = str
    message_mod.MessageSegment = object
    remember("nonebot.adapters.onebot.v11.message", message_mod)

    exception_mod = types.ModuleType("nonebot.exception")
    exception_mod.FinishedException = type("FinishedException", (Exception,), {})
    remember("nonebot.exception", exception_mod)

    rule_mod = types.ModuleType("nonebot.rule")
    rule_mod.to_me = lambda: None
    remember("nonebot.rule", rule_mod)

    permission_mod = types.ModuleType("nonebot.adapters.onebot.v11.permission")
    permission_mod.GROUP_ADMIN = object()
    permission_mod.GROUP_OWNER = object()
    remember("nonebot.adapters.onebot.v11.permission", permission_mod)

    apscheduler_mod = types.ModuleType("nonebot_plugin_apscheduler")
    apscheduler_mod.scheduler = object()
    remember("nonebot_plugin_apscheduler", apscheduler_mod)

    httpx_mod = types.ModuleType("httpx")
    httpx_mod.AsyncClient = object
    remember("httpx", httpx_mod)

    aiohttp_mod = types.ModuleType("aiohttp")
    aiohttp_mod.ClientSession = object
    remember("aiohttp", aiohttp_mod)

    aiosqlite_mod = types.ModuleType("aiosqlite")
    aiosqlite_mod.connect = None
    remember("aiosqlite", aiosqlite_mod)

    loguru_mod = types.ModuleType("loguru")
    loguru_mod.logger = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None)
    remember("loguru", loguru_mod)

    mute_mod = types.ModuleType("plugins.arteta_mute")
    mute_mod.is_muted = lambda *args, **kwargs: False
    remember("plugins.arteta_mute", mute_mod)

    render_mod = types.ModuleType("plugins.arteta_render")
    render_mod.text_to_tactical_board = lambda *args, **kwargs: None
    render_mod.html_to_image = lambda *args, **kwargs: None
    render_mod.needs_html_render = lambda *args, **kwargs: False
    render_mod.favorability_bar_chart = lambda *args, **kwargs: None
    render_mod.close_browser = lambda *args, **kwargs: None
    remember("plugins.arteta_render", render_mod)

    async def no_football_news(*args, **kwargs):
        return ""

    tools_mod = types.ModuleType("plugins.arteta_tools")
    tools_mod.register_config = lambda *args, **kwargs: None
    tools_mod.run_tool_loop = lambda *args, **kwargs: None
    tools_mod.maybe_answer_football_news_directly = no_football_news
    tools_mod.maybe_search_football_news_for_prompt = no_football_news
    remember("plugins.arteta_tools", tools_mod)

    knowledge_mod = types.ModuleType("plugins.arteta_knowledge")
    knowledge_mod.query_knowledge = lambda *args, **kwargs: ""
    remember("plugins.arteta_knowledge", knowledge_mod)

    memory_stub = types.ModuleType("plugins.arteta_memory")
    memory_stub.memory_store = memory_module.memory_store
    memory_stub.MemoryStore = memory_module.MemoryStore
    memory_stub.build_memory_document = memory_module.build_memory_document
    remember("plugins.arteta_memory", memory_stub)

    return previous


def restore_modules(previous):
    for name, module in previous.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


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


class ArtetaMemoryTests(unittest.TestCase):
    def test_build_memory_document_includes_speaker_identity_and_aliases(self):
        module = load_arteta_memory_module()

        content = module.build_memory_document(
            user_id="2648955710",
            nickname="Oiseaux Volants",
            aliases=["飞鸟", "Oiseaux Volants", "飞鸟"],
            user_msg="今天我踢球了",
            assistant_reply="踢球了？好事情！",
        )

        self.assertIn("Speaker ID: 2648955710", content)
        self.assertIn("Speaker Nickname: Oiseaux Volants", content)
        self.assertIn("Speaker Aliases: Oiseaux Volants、飞鸟", content)
        self.assertIn("User: 今天我踢球了", content)
        self.assertIn("Assistant: 踢球了？好事情！", content)

    def test_recent_messages_match_alias_query(self):
        memory_module = load_arteta_memory_module()
        previous = install_chat_import_stubs(memory_module)
        old_db_path = None
        try:
            spec = importlib.util.spec_from_file_location("arteta_chat_for_test", CHAT_MODULE_PATH)
            chat_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(chat_module)

            with tempfile.TemporaryDirectory() as tmpdir:
                db_path = str(Path(tmpdir) / "arteta.db")
                old_db_path = chat_module.DB_PATH
                chat_module.DB_PATH = db_path
                chat_module.init_db_safely()

                conn = sqlite3.connect(db_path)
                now = int(time.time())
                conn.execute(
                    "INSERT INTO players (user_id, group_id, nickname, favorability, level, profile_json, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        "2648955710",
                        "1104602373",
                        "Oiseaux Volants",
                        999999,
                        "传奇队长",
                        json.dumps({"nicknames": ["飞鸟", "Oiseaux Volants"]}, ensure_ascii=False),
                        now,
                    ),
                )
                conn.execute(
                    "INSERT INTO nicknames (user_id, group_id, nickname, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
                    ("2648955710", "1104602373", "飞鸟", now - 10, now),
                )
                conn.execute(
                    "INSERT INTO nicknames (user_id, group_id, nickname, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
                    ("2648955710", "1104602373", "Oiseaux Volants", now - 20, now - 5),
                )
                conn.execute(
                    "INSERT INTO messages (user_id, group_id, message, timestamp) VALUES (?, ?, ?, ?)",
                    ("2648955710", "1104602373", "今天我踢球了", now),
                )
                conn.commit()
                conn.close()

                result = chat_module.find_recent_messages_by_alias(
                    "1104602373",
                    "今天飞鸟说他干了什么",
                )

                self.assertEqual(1, len(result))
                self.assertEqual("2648955710", result[0]["user_id"])
                self.assertEqual("Oiseaux Volants", result[0]["nickname"])
                self.assertEqual("今天我踢球了", result[0]["message"])
        finally:
            if old_db_path is not None:
                chat_module.DB_PATH = old_db_path
            restore_modules(previous)

    def test_recent_messages_match_profile_alias_without_nickname_row(self):
        memory_module = load_arteta_memory_module()
        previous = install_chat_import_stubs(memory_module)
        old_db_path = None
        try:
            spec = importlib.util.spec_from_file_location("arteta_chat_for_test", CHAT_MODULE_PATH)
            chat_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(chat_module)

            with tempfile.TemporaryDirectory() as tmpdir:
                db_path = str(Path(tmpdir) / "arteta.db")
                old_db_path = chat_module.DB_PATH
                chat_module.DB_PATH = db_path
                chat_module.init_db_safely()

                conn = sqlite3.connect(db_path)
                now = int(time.time())
                conn.execute(
                    "INSERT INTO players (user_id, group_id, nickname, favorability, level, profile_json, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        "2648955710",
                        "1104602373",
                        "Oiseaux Volants",
                        999999,
                        "传奇队长",
                        json.dumps({"nicknames": ["飞鸟", "Oiseaux Volants"]}, ensure_ascii=False),
                        now,
                    ),
                )
                conn.execute(
                    "INSERT INTO nicknames (user_id, group_id, nickname, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
                    ("2648955710", "1104602373", "Oiseaux Volants", now - 20, now - 5),
                )
                conn.execute(
                    "INSERT INTO messages (user_id, group_id, message, timestamp) VALUES (?, ?, ?, ?)",
                    ("2648955710", "1104602373", "今天我踢球了", now),
                )
                conn.commit()
                conn.close()

                result = chat_module.find_recent_messages_by_alias(
                    "1104602373",
                    "今天飞鸟说他干了什么",
                )

                self.assertEqual(1, len(result))
                self.assertEqual("2648955710", result[0]["user_id"])
                self.assertEqual("飞鸟", result[0]["alias"])
                self.assertEqual("今天我踢球了", result[0]["message"])
        finally:
            if old_db_path is not None:
                chat_module.DB_PATH = old_db_path
            restore_modules(previous)

    def test_clear_group_memories_only_deletes_target_group(self):
        memory_module = load_arteta_memory_module()
        store = memory_module.MemoryStore()
        store.collection = FakeMemoryCollection()
        store._ready = True

        store.add_memory("100", "u1", "hello", "reply", nickname="A", aliases=[])
        store.add_memory("200", "u2", "world", "reply", nickname="B", aliases=[])

        deleted = store.clear_group_memories("100")

        self.assertEqual(1, deleted)
        self.assertEqual([], store.query_memories("100", "hello"))
        self.assertEqual(1, len(store.query_memories("200", "world")))

    def test_clear_group_memories_returns_zero_when_store_not_ready(self):
        memory_module = load_arteta_memory_module()
        store = memory_module.MemoryStore()
        store._ready = False

        deleted = store.clear_group_memories("100")

        self.assertEqual(0, deleted)


if __name__ == "__main__":
    unittest.main()
