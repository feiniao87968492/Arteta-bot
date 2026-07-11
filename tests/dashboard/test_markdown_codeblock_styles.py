from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_markdown_codeblocks_use_lighter_background():
    source = (ROOT / "dashboard/web/src/styles.css").read_text(encoding="utf-8")

    assert ".markdown-preview pre" in source
    assert "rgba(5, 7, 10, 0.64)" not in source
    assert "rgba(18, 24, 34, 0.96)" in source
