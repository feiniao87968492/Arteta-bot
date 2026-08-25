import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
LOGS_PAGE = os.path.join(REPO_ROOT, "dashboard", "web", "src", "pages", "LogsPage.tsx")


def read_logs_page():
    with open(LOGS_PAGE, "r", encoding="utf-8") as f:
        return f.read()


def test_logs_page_loads_selected_tail_by_default():
    source = read_logs_page()

    assert "await tail(nextSelected)" in source
    assert "const nextSelected" in source
    assert "setSelected(nextSelected)" in source
