import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
APP_FILE = os.path.join(REPO_ROOT, "dashboard", "web", "src", "App.tsx")
STYLES_FILE = os.path.join(REPO_ROOT, "dashboard", "web", "src", "styles.css")


def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_app_starts_on_launch_page_before_auth_or_dashboard_shell():
    source = read_file(APP_FILE)

    launch_markup = source.split('if (!enteredDashboard)', 1)[1].split('return (\n    <Shell page={page}', 1)[0]
    assert "enteredDashboard" in source
    assert "开始" in launch_markup
    assert "ARTETA BOT / MATCHDAY CONTROL" in launch_markup
    assert "arteta_bot控制面板" not in launch_markup
    assert "launch-panel" in launch_markup
    assert "LoginPage" not in source
    assert "authenticated" not in source
    assert "<Shell page={page}" in source
    assert source.index("launch-panel") < source.index("<Shell page={page}")


def test_launch_kicker_is_enlarged():
    source = read_file(STYLES_FILE)

    assert ".mission-kicker.launch-kicker" in source
    kicker_rule = source.split(".mission-kicker.launch-kicker", 1)[1].split("}", 1)[0]
    assert "font-size: clamp(26px, 5vw, 64px)" in kicker_rule
    assert "margin-bottom: 56px" in kicker_rule
    button_rule = source.split(".launch-start-button", 1)[1].split("}", 1)[0]
    assert "transform: translateY(24px)" in button_rule
