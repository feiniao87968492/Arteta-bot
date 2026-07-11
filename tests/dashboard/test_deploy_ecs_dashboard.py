import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
SCRIPT_PATH = os.path.join(REPO_ROOT, "deploy", "deploy_ecs.sh")


def _script():
    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def test_ecs_deploy_script_configures_dashboard_process():
    script = _script()

    assert "DASHBOARD_ADMIN_PASSWORD" in script
    assert "DASHBOARD_SECRET_KEY" in script
    assert "DASHBOARD_PUBLIC=true" in script
    assert "[program:arteta_dashboard]" in script
    assert "uvicorn dashboard.api.main:app" in script
    assert "ARTETA_DB_PATH=/opt/arteta_bot/arsenal_data.db" in script
    assert "ARTETA_CHROMA_DIR=/opt/arteta_bot/chroma_db" in script
    assert "DASHBOARD_LOGS_DIR=/opt/arteta_bot/logs" in script
    assert "DASHBOARD_WEB_DIST=/opt/arteta_bot/dashboard/web/dist" in script


def test_ecs_deploy_script_builds_dashboard_frontend():
    script = _script()

    assert "apt install -y" in script and "nodejs" in script and "npm" in script
    assert "npm --prefix \"$BOT_DIR/dashboard/web\" install" in script
    assert "npm --prefix \"$BOT_DIR/dashboard/web\" run build" in script


def test_ecs_deploy_script_preserves_prompt_registry():
    script = _script()

    assert "mkdir -p \"$BOT_DIR/config\"" in script
    assert "ARTETA_PROMPTS_FILE=/opt/arteta_bot/config/prompts.json" in script
    assert "config/prompts.json" in script
    assert "if [[ ! -f \"$BOT_DIR/config/prompts.json\" ]]" in script


def test_ecs_deploy_script_enables_sqlite_behavior_policy_store():
    script = _script()

    assert "mkdir -p \"$BOT_DIR/data\"" in script
    assert (
        "ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH=/opt/arteta_bot/data/agent_behavior_policy.db"
        in script
    )
