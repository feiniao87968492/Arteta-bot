import importlib.util
import sys
import types
import unittest
from pathlib import Path


HELP_MODULE_PATH = Path(__file__).resolve().parents[1] / "plugins" / "arteta_help.py"


def install_help_import_stubs():
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
    remember("nonebot", nonebot)

    adapter = types.ModuleType("nonebot.adapters.onebot.v11")
    adapter.Bot = object
    adapter.MessageEvent = type("MessageEvent", (), {})
    adapter.MessageSegment = type("MessageSegment", (), {"image": staticmethod(lambda payload: payload)})
    remember("nonebot.adapters.onebot.v11", adapter)

    render_mod = types.ModuleType("plugins.arteta_render")
    render_mod.text_to_tactical_board = lambda *args, **kwargs: b""
    render_mod.html_to_image = lambda *args, **kwargs: b""
    render_mod.needs_html_render = lambda *args, **kwargs: False
    remember("plugins.arteta_render", render_mod)

    return previous



def restore_modules(previous):
    for name, module in previous.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module



def load_arteta_help_module():
    previous = install_help_import_stubs()
    try:
        spec = importlib.util.spec_from_file_location("arteta_help_for_test", HELP_MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, previous
    except Exception:
        restore_modules(previous)
        raise


class BuildHelpTextTests(unittest.TestCase):
    def test_build_help_text_includes_clear_memory_admin_command(self):
        arteta_help, previous = load_arteta_help_module()
        try:
            text = arteta_help.build_help_text()

            self.assertIn(
                "clear/清除记忆/清空记忆：清空当前群的长期对话记忆（仅管理员）。",
                text,
            )
        finally:
            restore_modules(previous)


if __name__ == "__main__":
    unittest.main()
