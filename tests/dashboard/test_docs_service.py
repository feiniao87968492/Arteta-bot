from dashboard.api.services.docs_service import DocsService


def test_tree_and_read_markdown(tmp_path):
    docs = tmp_path / "Docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\nHello Arteta", encoding="utf-8")
    service = DocsService([str(docs)])

    tree = service.tree()

    assert tree[0]["name"] == "Docs"
    content = service.read_file("Docs/guide.md")
    assert "Hello Arteta" in content["content"]


def test_path_traversal_rejected(tmp_path):
    docs = tmp_path / "Docs"
    docs.mkdir()
    service = DocsService([str(docs)])

    try:
        service.read_file("Docs/../secret.txt")
    except ValueError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("path traversal was not rejected")


def test_search(tmp_path):
    docs = tmp_path / "knowledge_base"
    docs.mkdir()
    (docs / "tactics.md").write_text("# Press\nHigh press wins the ball", encoding="utf-8")
    service = DocsService([str(docs)])

    results = service.search("press")

    assert results[0]["path"] == "knowledge_base/tactics.md"
