import asyncio

from fastapi.testclient import TestClient

from dashboard.api.main import create_app
from dashboard.api.routers import config as config_router


CHAT_VALUES = {
    "DEEPSEEK_API_URL": "https://chat.example/v1/chat/completions",
    "DEEPSEEK_MODEL": "chat-model",
    "DEEPSEEK_API_KEY": "sk-chat-new",
    "DEEPSEEK_TEMPERATURE": "0.7",
}


def _auth_headers(client):
    login = client.post("/api/auth/login", json={"password": "secret"})
    assert login.status_code == 200
    token = login.json()["data"]["token"]
    return {"Authorization": "Bearer " + token}


def test_provider_config_requires_a_verified_login(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    monkeypatch.setenv("DASHBOARD_ENV_FILE", str(env_file))

    client = TestClient(create_app())

    assert client.get("/api/config/providers").status_code == 401
    assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    assert client.get("/api/config/providers", headers=_auth_headers(client)).status_code == 200


def test_provider_validation_receipt_uses_authenticated_subject(monkeypatch):
    actors = []

    class ProviderService:
        async def verify(self, provider_id, values, actor):
            actors.append(actor)
            return {"provider": provider_id, "receipt": "receipt", "expires_in": 300}

    class Audit:
        def record(self, *args, **kwargs):
            return None

    monkeypatch.setattr(config_router, "_provider_service", lambda: ProviderService())
    monkeypatch.setattr(config_router, "AuditService", lambda path: Audit())

    result = asyncio.run(
        config_router.validate_provider(
            "chat",
            config_router.ProviderCandidateRequest(values=CHAT_VALUES),
            {"sub": "operator-one"},
        )
    )

    assert result["data"]["receipt"] == "receipt"
    assert actors == ["operator-one"]


def test_provider_apply_uses_the_same_authenticated_subject(monkeypatch):
    actors = []

    class Settings:
        audit_log_path = "unused.log"
        readonly = False

    class ProviderService:
        def apply(self, provider_id, values, receipt, actor, restart):
            actors.append(actor)
            return {
                "provider": provider_id,
                "active": True,
                "persistence_succeeded": True,
                "initial_restart_failed": False,
                "rolled_back": False,
                "recovery_active": False,
                "recovery_restart_succeeded": False,
                "restart_error": "",
            }

    class Audit:
        def record(self, *args, **kwargs):
            return None

    monkeypatch.setattr(config_router, "get_settings", lambda: Settings())
    monkeypatch.setattr(config_router, "_provider_service", lambda: ProviderService())
    monkeypatch.setattr(config_router, "AuditService", lambda path: Audit())

    result = config_router.apply_provider(
        "chat",
        config_router.ProviderApplyRequest(values=CHAT_VALUES, receipt="receipt"),
        {"sub": "operator-one"},
    )

    assert result["data"]["active"] is True
    assert actors == ["operator-one"]


def test_legacy_single_field_config_endpoints_are_removed(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original = "DEEPSEEK_MODEL=old-model\n"
    env_file.write_text(original, encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    monkeypatch.setenv("DASHBOARD_ENV_FILE", str(env_file))

    client = TestClient(create_app())
    headers = _auth_headers(client)

    assert client.get("/api/config/keys", headers=headers).status_code == 404
    assert client.get("/api/config/keys/DEEPSEEK_MODEL/test", headers=headers).status_code == 404
    assert client.post("/api/config/keys", headers=headers, json={"name": "DEEPSEEK_MODEL", "value": "new-model"}).status_code in (404, 405)
    assert client.post("/api/config/restart-bot", headers=headers).status_code in (404, 405)
    assert env_file.read_text(encoding="utf-8") == original


def test_provider_config_api_verifies_before_applying_and_restarts(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original = "DEEPSEEK_API_KEY=sk-chat-old\nOTHER=value\n"
    env_file.write_text(original, encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    monkeypatch.setenv("DASHBOARD_ENV_FILE", str(env_file))
    monkeypatch.setenv("DASHBOARD_READONLY", "false")
    calls = []

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class Client:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    class RestartResult:
        returncode = 0
        stdout = "restarted\n"
        stderr = ""

    monkeypatch.setattr("dashboard.api.services.provider_config_service.httpx.AsyncClient", Client)
    monkeypatch.setattr(config_router.subprocess, "run", lambda *args, **kwargs: RestartResult())
    client = TestClient(create_app())
    headers = _auth_headers(client)

    listed = client.get("/api/config/providers", headers=headers)
    assert listed.status_code == 200
    chat = next(item for item in listed.json()["data"] if item["id"] == "chat")
    assert chat["values"]["DEEPSEEK_API_KEY"] != "sk-chat-old"

    verified = client.post("/api/config/providers/chat/validate", headers=headers, json={"values": CHAT_VALUES})
    assert verified.status_code == 200
    assert env_file.read_text(encoding="utf-8") == original
    assert calls[0][0] == "https://chat.example/v1/chat/completions"

    applied = client.post(
        "/api/config/providers/chat/apply",
        headers=headers,
        json={"values": CHAT_VALUES, "receipt": verified.json()["data"]["receipt"]},
    )
    assert applied.status_code == 200
    assert applied.json()["data"]["active"] is True
    assert "DEEPSEEK_API_KEY=sk-chat-new" in env_file.read_text(encoding="utf-8")


def test_provider_apply_rejects_readonly_mode_without_restarting(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY=sk-chat-old\n", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    monkeypatch.setenv("DASHBOARD_ENV_FILE", str(env_file))
    monkeypatch.setenv("DASHBOARD_READONLY", "true")
    called = False

    def forbidden_restart(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(config_router.subprocess, "run", forbidden_restart)
    client = TestClient(create_app())
    response = client.post(
        "/api/config/providers/chat/apply",
        headers=_auth_headers(client),
        json={"values": CHAT_VALUES, "receipt": "unneeded"},
    )

    assert response.status_code == 403
    assert called is False
    assert env_file.read_text(encoding="utf-8") == "DEEPSEEK_API_KEY=sk-chat-old\n"
