import importlib.util
import sys
import types
import unittest
from pathlib import Path


CHAT_MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "arteta_chat.py"
MEMORY_MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "arteta_memory.py"


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
        spec = importlib.util.spec_from_file_location("arteta_memory_for_chat_command_test", MEMORY_MODULE_PATH)
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

        async def finish(self, message=None):
            return message

    nonebot.on_command = lambda *args, **kwargs: DummyMatcher()
    nonebot.on_message = lambda *args, **kwargs: DummyMatcher()
    nonebot.on_notice = lambda *args, **kwargs: DummyMatcher()

    class DummyDriver(object):
        def __init__(self):
            self.config = types.SimpleNamespace(dict=lambda: {}, model_dump=lambda: {})

        def on_shutdown(self, func):
            return func

    nonebot.get_driver = lambda: DummyDriver()
    remember("nonebot", nonebot)

    rule_mod = types.ModuleType("nonebot.rule")
    rule_mod.to_me = lambda: None
    remember("nonebot.rule", rule_mod)

    adapter = types.ModuleType("nonebot.adapters.onebot.v11")
    adapter.Bot = object
    adapter.MessageEvent = type("MessageEvent", (), {})
    adapter.GroupMessageEvent = type("GroupMessageEvent", (), {})
    adapter.Message = str
    adapter.NoticeEvent = type("NoticeEvent", (), {})
    adapter.MessageSegment = object
    remember("nonebot.adapters.onebot.v11", adapter)

    exception_mod = types.ModuleType("nonebot.exception")
    exception_mod.FinishedException = type("FinishedException", (Exception,), {})
    remember("nonebot.exception", exception_mod)

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

    prompt_service_mod = types.ModuleType("dashboard.api.services.prompt_service")
    prompt_service_mod.get_prompt = lambda key, default: default
    remember("dashboard.api.services.prompt_service", prompt_service_mod)

    mute_mod = types.ModuleType("plugins.arteta_mute")
    mute_mod.is_muted = lambda *args, **kwargs: False
    remember("plugins.arteta_mute", mute_mod)

    power_mod = types.ModuleType("plugins.arteta_power")
    power_mod.is_bot_enabled = lambda: True
    remember("plugins.arteta_power", power_mod)

    render_mod = types.ModuleType("plugins.arteta_render")
    render_mod.text_to_tactical_board = lambda *args, **kwargs: None
    render_mod.html_to_image = lambda *args, **kwargs: None
    render_mod.needs_html_render = lambda *args, **kwargs: False
    render_mod.favorability_bar_chart = lambda *args, **kwargs: None
    render_mod.close_browser = lambda *args, **kwargs: None
    remember("plugins.arteta_render", render_mod)

    tools_mod = types.ModuleType("plugins.arteta_tools")
    tools_mod.register_config = lambda *args, **kwargs: None
    tools_mod.run_tool_loop = lambda *args, **kwargs: None
    remember("plugins.arteta_tools", tools_mod)

    vision_mod = types.ModuleType("plugins.arteta_vision")
    vision_mod.VisionConfig = type("VisionConfig", (), {})
    vision_mod.analyze_image_base64 = lambda *args, **kwargs: None
    vision_mod.detect_image_format = lambda *args, **kwargs: "jpeg"
    remember("plugins.arteta_vision", vision_mod)

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


def load_arteta_chat_module():
    memory_module = load_arteta_memory_module()
    previous = install_chat_import_stubs(memory_module)
    try:
        spec = importlib.util.spec_from_file_location("arteta_chat_for_command_test", CHAT_MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, previous
    except Exception:
        restore_modules(previous)
        raise


class ClearGroupMemoryCommandTests(unittest.TestCase):
    def test_can_clear_group_memory_allows_admin_in_group(self):
        arteta_chat, previous = load_arteta_chat_module()
        try:
            event = types.SimpleNamespace(group_id=123)

            allowed, reason = arteta_chat.can_clear_group_memory(event, "2648955710", "2648955710")

            self.assertTrue(allowed)
            self.assertEqual("", reason)
        finally:
            restore_modules(previous)

    def test_can_clear_group_memory_rejects_non_admin(self):
        arteta_chat, previous = load_arteta_chat_module()
        try:
            event = types.SimpleNamespace(group_id=123)

            allowed, reason = arteta_chat.can_clear_group_memory(event, "111", "2648955710")

            self.assertFalse(allowed)
            self.assertIn("管理员", reason)
        finally:
            restore_modules(previous)

    def test_can_clear_group_memory_rejects_private_chat(self):
        arteta_chat, previous = load_arteta_chat_module()
        try:
            event = types.SimpleNamespace()

            allowed, reason = arteta_chat.can_clear_group_memory(event, "2648955710", "2648955710")

            self.assertFalse(allowed)
            self.assertIn("群聊", reason)
        finally:
            restore_modules(previous)

    def test_clear_group_memory_for_group_uses_current_group(self):
        arteta_chat, previous = load_arteta_chat_module()
        try:
            calls = []

            def fake_clear(group_id):
                calls.append(group_id)
                return 3

            arteta_chat.memory_store.clear_group_memories = fake_clear

            message = arteta_chat.clear_group_memory_for_group("543915926")

            self.assertEqual(["543915926"], calls)
            self.assertIn("3 条", message)
        finally:
            restore_modules(previous)


if __name__ == "__main__":
    unittest.main()
