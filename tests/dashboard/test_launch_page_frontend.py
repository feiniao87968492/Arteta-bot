import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
APP_FILE = os.path.join(REPO_ROOT, "dashboard", "web", "src", "App.tsx")
STYLES_FILE = os.path.join(REPO_ROOT, "dashboard", "web", "src", "styles.css")
CLIENT_FILE = os.path.join(REPO_ROOT, "dashboard", "web", "src", "api", "client.ts")
CONFIG_PAGE_FILE = os.path.join(REPO_ROOT, "dashboard", "web", "src", "pages", "ConfigPage.tsx")


def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_app_requires_login_before_showing_the_dashboard():
    source = read_file(APP_FILE)

    launch_markup = source.split('if (!enteredDashboard)', 1)[1].split('return (\n    <Shell page={page}', 1)[0]
    assert "enteredDashboard" in source
    assert "开始" in launch_markup
    assert "ARTETA BOT / MATCHDAY CONTROL" in launch_markup
    assert "arteta_bot控制面板" not in launch_markup
    assert "launch-panel" in launch_markup
    assert "import { LoginPage } from './pages/LoginPage';" in source
    assert "const [loginRequested, setLoginRequested] = useState(false);" in source
    assert "onClick={() => setLoginRequested(true)}" in launch_markup
    assert "<LoginPage onLogin={() => setEnteredDashboard(true)} />" in source
    assert "<Shell page={page}" in source
    assert source.index("launch-panel") < source.index("<Shell page={page}")


def test_unauthorized_api_response_returns_the_dashboard_to_login():
    app_source = read_file(APP_FILE)
    client_source = read_file(CLIENT_FILE)

    assert "DASHBOARD_UNAUTHORIZED_EVENT" in client_source
    assert "window.dispatchEvent(new Event(DASHBOARD_UNAUTHORIZED_EVENT))" in client_source
    assert "subscribeToUnauthorized" in app_source
    assert "setEnteredDashboard(false)" in app_source
    assert "setLoginRequested(true)" in app_source


def test_config_page_makes_initial_loading_failure_visible_and_retryable():
    source = read_file(CONFIG_PAGE_FILE)

    assert "const [loadError, setLoadError] = useState('');" in source
    assert "setLoadError(error instanceof Error ? error.message : 'Failed to load provider configuration')" in source
    assert "Retry loading configuration" in source


def test_launch_kicker_is_enlarged():
    source = read_file(STYLES_FILE)

    assert ".mission-kicker.launch-kicker" in source
    kicker_rule = source.split(".mission-kicker.launch-kicker", 1)[1].split("}", 1)[0]
    assert "font-size: clamp(26px, 5vw, 64px)" in kicker_rule
    assert "margin-bottom: 56px" in kicker_rule
    button_rule = source.split(".launch-start-button", 1)[1].split("}", 1)[0]
    assert "transform: translateY(24px)" in button_rule
