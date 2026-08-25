import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
DOCS_PAGE = os.path.join(REPO_ROOT, "dashboard", "web", "src", "pages", "DocsPage.tsx")
DOCS_STYLES = os.path.join(REPO_ROOT, "dashboard", "web", "src", "styles.css")


def read_docs_page():
    with open(DOCS_PAGE, "r", encoding="utf-8") as f:
        return f.read()


def read_docs_styles():
    with open(DOCS_STYLES, "r", encoding="utf-8") as f:
        return f.read()


def test_docs_page_renders_markdown_preview_instead_of_raw_pre():
    source = read_docs_page()
    assert "markdown-preview" in source
    assert "dangerouslySetInnerHTML" in source
    assert "<pre>{file?.content" not in source


def test_docs_search_sits_above_wide_reader_layout():
    source = read_docs_page()
    assert "docs-search-panel" in source
    assert "docs-content-layout" in source
    assert "docs-reader-panel" in source
    assert source.index("docs-search-panel") < source.index("docs-content-layout")
    assert "three-column docs-layout" not in source


def test_docs_reader_uses_page_scroll_instead_of_internal_scroll():
    source = read_docs_styles()
    assert ".docs-reader-panel .markdown-preview" in source
    reader_rule = source.split(".docs-reader-panel .markdown-preview", 1)[1].split("}", 1)[0]
    assert "max-height: none" in reader_rule
    assert "overflow: visible" in reader_rule


def test_docs_page_labels_are_chinese():
    source = read_docs_page()
    assert "文档目录" in source
    assert "搜索文档和知识库" in source
    assert "Markdown 预览" in source
    assert "Select a markdown file" not in source
