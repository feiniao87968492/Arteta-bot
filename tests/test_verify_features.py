import argparse
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "verify_features.py"
spec = importlib.util.spec_from_file_location("verify_features", MODULE_PATH)
verify_features = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_features)


class VerifyFeaturesTests(unittest.TestCase):
    def make_context(self, root_dir: str) -> object:
        run_dir = Path(root_dir) / "run"
        artifacts_dir = run_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        return verify_features.RunContext(
            args=argparse.Namespace(
                suites=None,
                online=False,
                allow_side_effects=False,
                output_dir=str(Path(root_dir) / "out"),
                fail_fast=False,
                json_only=False,
                list_suites=False,
                cases=None,
            ),
            repo_root=str(Path(root_dir)),
            run_dir=str(run_dir),
            artifacts_dir=str(artifacts_dir),
        )

    def test_render_html_to_image_skips_when_playwright_browser_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            fixture_path = repo_root / "tests" / "fixtures" / "markdown" / "render_sample.md"
            fixture_path.parent.mkdir(parents=True, exist_ok=True)
            fixture_path.write_text("# verify\n", encoding="utf-8")
            ctx = self.make_context(tmpdir)

            async def fake_html_to_image(_markdown: str) -> bytes:
                raise RuntimeError(
                    "BrowserType.launch: Executable doesn't exist at C:/ms-playwright/chromium/chrome.exe"
                )

            async def fake_close_browser() -> None:
                return None

            fake_render = type(
                "FakeRenderModule",
                (),
                {
                    "html_to_image": staticmethod(fake_html_to_image),
                    "close_browser": staticmethod(fake_close_browser),
                },
            )

            with mock.patch.object(verify_features, "import_module", return_value=fake_render):
                result = verify_features.safe_case(
                    "render",
                    "html_to_image",
                    verify_features.render_html_to_image,
                )(ctx)

            self.assertEqual(verify_features.STATUS_SKIP, result.status)
            self.assertIn("playwright", result.message.lower())

    def test_render_html_to_image_uses_single_asyncio_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            fixture_path = repo_root / "tests" / "fixtures" / "markdown" / "render_sample.md"
            fixture_path.parent.mkdir(parents=True, exist_ok=True)
            fixture_path.write_text("# verify\n", encoding="utf-8")
            ctx = self.make_context(tmpdir)

            fake_render = type("FakeRenderModule", (), {})
            fake_render.calls = []

            async def fake_html_to_image(_markdown: str) -> bytes:
                fake_render.calls.append("html")
                return b"\x89PNGstub"

            async def fake_close_browser() -> None:
                fake_render.calls.append("close")

            fake_render.html_to_image = staticmethod(fake_html_to_image)
            fake_render.close_browser = staticmethod(fake_close_browser)

            async def fake_runner(coro):
                return await coro

            def run_once(coro):
                return __import__("asyncio").get_event_loop_policy().new_event_loop().run_until_complete(fake_runner(coro))

            with mock.patch.object(verify_features, "import_module", return_value=fake_render), \
                 mock.patch.object(verify_features.asyncio, "run", side_effect=run_once) as mocked_run:
                result = verify_features.render_html_to_image(ctx)

            self.assertEqual(verify_features.STATUS_PASS, result.status)
            self.assertEqual(["html", "close"], fake_render.calls)
            self.assertEqual(1, mocked_run.call_count)

    def test_prepare_isolated_runtime_sets_storage_overrides(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self.make_context(tmpdir)
            old_db = os.environ.get("ARTETA_DB_PATH")
            old_swears = os.environ.get("ARTETA_SWEARS_FILE")
            try:
                if "ARTETA_DB_PATH" in os.environ:
                    del os.environ["ARTETA_DB_PATH"]
                if "ARTETA_SWEARS_FILE" in os.environ:
                    del os.environ["ARTETA_SWEARS_FILE"]

                verify_features.prepare_isolated_runtime(ctx)

                db_path = os.environ.get("ARTETA_DB_PATH", "")
                swears_path = os.environ.get("ARTETA_SWEARS_FILE", "")
                runtime_dir = Path(tmpdir) / "run" / "runtime"
                self.assertTrue(db_path.endswith("verification.db"))
                self.assertTrue(swears_path.endswith("arteta_swears.json"))
                self.assertIn(str(runtime_dir), db_path)
                self.assertIn(str(runtime_dir), swears_path)
                self.assertTrue(runtime_dir.is_dir())
            finally:
                if old_db is None:
                    os.environ.pop("ARTETA_DB_PATH", None)
                else:
                    os.environ["ARTETA_DB_PATH"] = old_db
                if old_swears is None:
                    os.environ.pop("ARTETA_SWEARS_FILE", None)
                else:
                    os.environ["ARTETA_SWEARS_FILE"] = old_swears

    def test_registry_contains_football_news_suite(self):
        registry = verify_features.build_registry()
        self.assertIn("football_news", registry)
        case_names = [name for name, _case in registry["football_news"].cases]
        self.assertIn("offline_roundtrip", case_names)

    def test_registry_contains_agent_registry_suite(self):
        registry = verify_features.build_registry()
        self.assertIn("agent_registry", registry)
        self.assertIn("agent_permissions", registry)
        self.assertIn("agent_loop", registry)
        case_names = [name for name, _case in registry["agent_registry"].cases]
        self.assertIn("registry_has_tools", case_names)
        self.assertIn("permission_gates", case_names)
        self.assertIn("executor_error_paths", case_names)
        self.assertIn("phase2_read_tools", case_names)
        self.assertIn("phase3_read_tools", case_names)
        self.assertIn("phase3_safe_write_tools", case_names)
        self.assertIn("phase4_confirm_write_tools", case_names)
        self.assertIn("phase5_admin_tools", case_names)
        permission_case_names = [name for name, _case in registry["agent_permissions"].cases]
        self.assertIn("permission_gates", permission_case_names)
        self.assertIn("phase4_confirm_write_tools", permission_case_names)
        self.assertIn("phase5_admin_tools", permission_case_names)
        loop_case_names = [name for name, _case in registry["agent_loop"].cases]
        self.assertIn("executor_error_paths", loop_case_names)

    def test_registry_contains_explicit_personality_manual_suite_only(self):
        registry = verify_features.build_registry()

        self.assertIn("personality_manual", registry)
        case_names = [name for name, _case in registry["personality_manual"].cases]
        self.assertIn("manual_evidence_complete", case_names)
        self.assertNotIn("manual_evidence_complete", [name for name, _case in registry["core"].cases])
        self.assertNotIn("manual_evidence_complete", [name for name, _case in registry["all"].cases])

    def test_personality_manual_suite_fails_until_real_evidence_is_filled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self.make_context(tmpdir)
            ctx.repo_root = verify_features.REPO_ROOT

            result = verify_features.personality_manual_evidence_complete(ctx)

            self.assertEqual(verify_features.STATUS_FAIL, result.status)
            self.assertIn("manual evidence incomplete", result.message)
            self.assertEqual(12, result.details["sample_rows"])
            self.assertEqual(5, result.details["before_after_rows"])
            self.assertGreater(len(result.details["errors"]), 0)

    def test_agent_registry_web_access_offline_ignores_live_grok_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self.make_context(tmpdir)
            web_access = verify_features.import_module("plugins.arteta_agent.tools.web_access")
            old_env = {
                "ARTETA_GROKSEARCH_API_URL": os.environ.get("ARTETA_GROKSEARCH_API_URL"),
                "ARTETA_GROKSEARCH_API_KEY": os.environ.get("ARTETA_GROKSEARCH_API_KEY"),
                "ARTETA_GROKSEARCH_MODEL": os.environ.get("ARTETA_GROKSEARCH_MODEL"),
            }
            old_search = web_access._groksearch_search
            old_fetch = web_access._groksearch_fetch
            old_config_attr = web_access._config_attr

            async def fake_grok_search(query, max_results, freshness="recent"):
                return [{
                    "title": "(GrokSearch)",
                    "href": "https://www.arsenal.com/news/official-update",
                    "body": "配置错误: TAVILY_API_KEY 和 FIRECRAWL_API_KEY 均未配置",
                    "_backend": "grok",
                }]

            async def fake_grok_fetch(url):
                return "配置错误: TAVILY_API_KEY 和 FIRECRAWL_API_KEY 均未配置"

            try:
                os.environ["ARTETA_GROKSEARCH_API_URL"] = "https://live-grok.example"
                os.environ["ARTETA_GROKSEARCH_API_KEY"] = "unit-test-key"
                os.environ["ARTETA_GROKSEARCH_MODEL"] = "unit-test-model"
                web_access._groksearch_search = fake_grok_search
                web_access._groksearch_fetch = fake_grok_fetch
                web_access._config_attr = lambda name: "unit-test-config" if "GROKSEARCH" in name else ""

                result = verify_features.agent_registry_web_access_offline(ctx)

                self.assertEqual(verify_features.STATUS_PASS, result.status)
                self.assertNotIn("[grok]", result.details["verified"])
            finally:
                web_access._groksearch_search = old_search
                web_access._groksearch_fetch = old_fetch
                web_access._config_attr = old_config_attr
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_agent_registry_permission_gates_match_pending_action_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self.make_context(tmpdir)

            result = verify_features.agent_registry_permission_gates(ctx)

            self.assertEqual(verify_features.STATUS_PASS, result.status)

    def test_agent_loop_verifier_uses_strict_tool_schemas(self):
        cases = [
            verify_features.agent_loop_forces_ui_preference_tool,
            verify_features.agent_loop_forces_reply_body_ui_preference_tool,
            verify_features.agent_loop_allows_llm_to_choose_web_verification_tool,
            verify_features.agent_loop_forces_explicit_memory_tool,
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self.make_context(tmpdir)
            for case in cases:
                result = case(ctx)
                self.assertEqual(
                    verify_features.STATUS_PASS,
                    result.status,
                    "%s failed with details %r" % (result.case, result.details),
                )


if __name__ == "__main__":
    unittest.main()
