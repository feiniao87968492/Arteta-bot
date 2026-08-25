import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
SCRIPT_PATH = os.path.join(REPO_ROOT, "start_dashboard.ps1")


def test_dashboard_start_script_exists_and_launches_services():
    assert os.path.exists(SCRIPT_PATH)
    with open(SCRIPT_PATH, "r", encoding="utf-8-sig") as f:
        script = f.read()
    assert "DASHBOARD_ADMIN_PASSWORD" in script
    assert "DASHBOARD_SECRET_KEY" in script
    assert "uvicorn dashboard.api.main:app" in script
    assert "npm --prefix" in script
    assert "dashboard/web" in script
    assert "http://localhost:5173" in script


def test_dashboard_start_script_supports_ecs_sync_mode():
    with open(SCRIPT_PATH, "r", encoding="utf-8-sig") as f:
        script = f.read()

    assert "[switch]$EcsSync" in script
    assert "$RemoteDbPath" in script
    assert "$LocalDbPath" in script
    assert "$env:ARTETA_DB_PATH" in script
    assert "tools/sync_ecs_sqlite.py" in script
    assert "--once" in script
    assert "--interval" in script
