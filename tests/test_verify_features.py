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


if __name__ == "__main__":
    unittest.main()
