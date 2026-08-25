import asyncio

import httpx
import pytest

from dashboard.api.services.env_service import EnvService
from dashboard.api.services.provider_config_service import (
    ProviderConfigError,
    ProviderConfigService,
)


CHAT_VALUES = {
    "DEEPSEEK_API_URL": "https://chat.example/v1/chat/completions",
    "DEEPSEEK_MODEL": "chat-model",
    "DEEPSEEK_API_KEY": "sk-chat-new",
    "DEEPSEEK_TEMPERATURE": "0.7",
}

PROVIDER_VALUES = {
    "algorithm": {
        "ALGO_API_URL": "https://algo.example/v1/chat/completions",
        "ALGO_MODEL": "algo-model",
        "ALGO_API_KEY": "sk-algo",
    },
    "image_generation": {
        "IMAGE_API_URL": "https://image.example/v1",
        "IMAGE_MODEL": "image-model",
        "IMAGE_API_KEY": "sk-image",
    },
    "vision": {
        "VISION_API_URL": "https://vision.example/v1",
        "VISION_MODEL": "vision-model",
        "VISION_API_KEY": "sk-vision",
        "VISION_TIMEOUT": "30",
    },
    "football_data": {"FOOTBALL_API_TOKEN": "football-token"},
    "grok_search": {
        "ARTETA_GROKSEARCH_API_URL": "https://grok.example/v1",
        "ARTETA_GROKSEARCH_MODEL": "grok-model",
        "ARTETA_GROKSEARCH_API_KEY": "sk-grok",
        "ARTETA_GROKSEARCH_TIMEOUT": "30",
    },
    "x_fetch": {
        "ARTETA_X_FETCH_API_URL": "https://x-fetch.example/v1",
        "ARTETA_X_FETCH_API_KEY": "sk-x-fetch",
    },
}


class _Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {"choices": [{"message": {"content": "ok"}}]}
        self.text = text

    def json(self):
        return self._payload


class _RestartResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_list_providers_keeps_service_groups_independent(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DEEPSEEK_API_URL=https://chat.example/v1/chat/completions\n"
        "DEEPSEEK_MODEL=chat-model\n"
        "DEEPSEEK_API_KEY=sk-chat-old\n"
        "DEEPSEEK_TEMPERATURE=0.9\n"
        "IMAGE_API_URL=https://image.example\n"
        "IMAGE_MODEL=image-model\n"
        "IMAGE_API_KEY=sk-image-old\n",
        encoding="utf-8",
    )
    service = ProviderConfigService(EnvService(str(env_file), []))

    providers = {item["id"]: item for item in service.list_providers()}

    assert set(providers) == {
        "chat",
        "algorithm",
        "image_generation",
        "vision",
        "football_data",
        "grok_search",
        "x_fetch",
    }
    assert providers["chat"]["values"]["DEEPSEEK_API_URL"] == "https://chat.example/v1/chat/completions"
    assert providers["chat"]["values"]["DEEPSEEK_API_KEY"] != "sk-chat-old"
    assert providers["image_generation"]["values"]["IMAGE_API_KEY"] != "sk-image-old"
    assert "IMAGE_API_KEY" not in providers["chat"]["values"]
    assert "DEEPSEEK_API_KEY" not in providers["image_generation"]["values"]


def test_verify_chat_uses_candidate_without_writing_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original = "DEEPSEEK_API_KEY=sk-chat-old\n"
    env_file.write_text(original, encoding="utf-8")
    calls = []

    class _Client:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            calls.append((url, self.timeout, kwargs))
            return _Response()

    monkeypatch.setattr("dashboard.api.services.provider_config_service.httpx.AsyncClient", _Client)
    service = ProviderConfigService(EnvService(str(env_file), []))

    result = asyncio.run(service.verify("chat", CHAT_VALUES, actor="admin"))

    assert result["provider"] == "chat"
    assert result["receipt"]
    assert env_file.read_text(encoding="utf-8") == original
    assert calls == [
        (
            "https://chat.example/v1/chat/completions",
            20.0,
            {
                "headers": {"Authorization": "Bearer sk-chat-new"},
                "json": {
                    "model": "chat-model",
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                    "temperature": 0,
                },
            },
        )
    ]


def test_verify_rejects_a_value_that_could_inject_environment_lines(tmp_path):
    env_file = tmp_path / ".env"
    service = ProviderConfigService(EnvService(str(env_file), []))
    malicious = dict(CHAT_VALUES, DEEPSEEK_API_KEY="sk-safe\nOTHER=overwritten")

    with pytest.raises(ProviderConfigError) as exc:
        asyncio.run(service.verify("chat", malicious))

    assert exc.value.code == "invalid_candidate"
    assert not env_file.exists()


def test_provider_candidate_must_include_every_owned_field(tmp_path):
    service = ProviderConfigService(EnvService(str(tmp_path / ".env"), []))
    incomplete = dict(CHAT_VALUES)
    del incomplete["DEEPSEEK_TEMPERATURE"]

    with pytest.raises(ProviderConfigError) as exc:
        asyncio.run(service.verify("chat", incomplete))

    assert exc.value.code == "invalid_candidate"


def test_apply_rejects_a_candidate_that_differs_from_verified_values(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original = "DEEPSEEK_API_KEY=sk-chat-old\n"
    env_file.write_text(original, encoding="utf-8")

    class _Client:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            return _Response()

    monkeypatch.setattr("dashboard.api.services.provider_config_service.httpx.AsyncClient", _Client)
    service = ProviderConfigService(EnvService(str(env_file), []))
    receipt = asyncio.run(service.verify("chat", CHAT_VALUES, actor="admin"))["receipt"]
    changed_values = dict(CHAT_VALUES, DEEPSEEK_MODEL="other-model")

    with pytest.raises(ProviderConfigError) as exc:
        service.apply("chat", changed_values, receipt, actor="admin", restart=lambda: _RestartResult())

    assert exc.value.code == "invalid_receipt"
    assert env_file.read_text(encoding="utf-8") == original


def test_receipt_expires_and_cannot_be_reused(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    clock = [100.0]

    class _Client:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            return _Response()

    monkeypatch.setattr("dashboard.api.services.provider_config_service.httpx.AsyncClient", _Client)
    service = ProviderConfigService(EnvService(str(env_file), []), now=lambda: clock[0])
    expired_receipt = asyncio.run(service.verify("chat", CHAT_VALUES))["receipt"]
    clock[0] += 301.0

    with pytest.raises(ProviderConfigError) as expired:
        service.apply("chat", CHAT_VALUES, expired_receipt, restart=lambda: _RestartResult())
    assert expired.value.code == "invalid_receipt"

    clock[0] = 1000.0
    receipt = asyncio.run(service.verify("chat", CHAT_VALUES))["receipt"]
    assert service.apply("chat", CHAT_VALUES, receipt, restart=lambda: _RestartResult())["active"] is True
    with pytest.raises(ProviderConfigError) as reused:
        service.apply("chat", CHAT_VALUES, receipt, restart=lambda: _RestartResult())
    assert reused.value.code == "invalid_receipt"


def test_receipt_is_bound_to_the_verified_provider(monkeypatch, tmp_path):
    class _Client:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            return _Response()

    monkeypatch.setattr("dashboard.api.services.provider_config_service.httpx.AsyncClient", _Client)
    service = ProviderConfigService(EnvService(str(tmp_path / ".env"), []))
    receipt = asyncio.run(service.verify("chat", CHAT_VALUES, actor="admin"))["receipt"]

    with pytest.raises(ProviderConfigError) as exc:
        service.apply("algorithm", PROVIDER_VALUES["algorithm"], receipt, restart=lambda: _RestartResult())

    assert exc.value.code == "invalid_receipt"


def test_remote_verification_failures_do_not_mutate_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original = "DEEPSEEK_API_KEY=sk-chat-old\n"
    env_file.write_text(original, encoding="utf-8")

    class _Client:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            raise httpx.ReadTimeout("provider timed out")

    monkeypatch.setattr("dashboard.api.services.provider_config_service.httpx.AsyncClient", _Client)
    service = ProviderConfigService(EnvService(str(env_file), []))

    with pytest.raises(ProviderConfigError) as exc:
        asyncio.run(service.verify("chat", CHAT_VALUES))

    assert exc.value.code == "verification_failed"
    assert env_file.read_text(encoding="utf-8") == original


def test_credential_failure_is_rejected_without_mutating_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original = "DEEPSEEK_API_KEY=sk-chat-old\n"
    env_file.write_text(original, encoding="utf-8")

    class _Client:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            return _Response(status_code=401, payload={"error": "invalid key"})

    monkeypatch.setattr("dashboard.api.services.provider_config_service.httpx.AsyncClient", _Client)
    service = ProviderConfigService(EnvService(str(env_file), []))

    with pytest.raises(ProviderConfigError) as exc:
        asyncio.run(service.verify("chat", CHAT_VALUES))

    assert exc.value.code == "verification_failed"
    assert env_file.read_text(encoding="utf-8") == original


def test_unsupported_image_model_is_rejected_without_mutating_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original = "IMAGE_API_KEY=sk-image-old\n"
    env_file.write_text(original, encoding="utf-8")

    class _Client:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, **kwargs):
            return _Response(payload={"data": [{"id": "other-model"}]})

    monkeypatch.setattr("dashboard.api.services.provider_config_service.httpx.AsyncClient", _Client)
    service = ProviderConfigService(EnvService(str(env_file), []))

    with pytest.raises(ProviderConfigError) as exc:
        asyncio.run(service.verify("image_generation", PROVIDER_VALUES["image_generation"]))

    assert exc.value.code == "model_unavailable"
    assert env_file.read_text(encoding="utf-8") == original


def test_bad_football_response_shape_is_rejected_without_mutating_env(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original = "FOOTBALL_API_TOKEN=old-token\n"
    env_file.write_text(original, encoding="utf-8")

    class _Client:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, **kwargs):
            return _Response(payload={"competition": "PL"})

    monkeypatch.setattr("dashboard.api.services.provider_config_service.httpx.AsyncClient", _Client)
    service = ProviderConfigService(EnvService(str(env_file), []))

    with pytest.raises(ProviderConfigError) as exc:
        asyncio.run(service.verify("football_data", PROVIDER_VALUES["football_data"]))

    assert exc.value.code == "verification_failed"
    assert env_file.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("provider_id", sorted(PROVIDER_VALUES))
def test_each_non_chat_provider_uses_its_own_minimal_verification_request(monkeypatch, tmp_path, provider_id):
    calls = []

    class _Client:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, **kwargs):
            calls.append(("GET", url, self.timeout, kwargs))
            if provider_id == "image_generation":
                return _Response(payload={"data": [{"id": "image-model"}]})
            return _Response(payload={"standings": []})

        async def post(self, url, **kwargs):
            calls.append(("POST", url, self.timeout, kwargs))
            if provider_id == "vision":
                return _Response(payload={"choices": [{"message": {"content": "image"}}]})
            return _Response(payload={})

    monkeypatch.setattr("dashboard.api.services.provider_config_service.httpx.AsyncClient", _Client)
    service = ProviderConfigService(EnvService(str(tmp_path / ".env"), []))

    result = asyncio.run(service.verify(provider_id, PROVIDER_VALUES[provider_id]))

    assert result["provider"] == provider_id
    assert len(calls) == 1
    method, url, _timeout, kwargs = calls[0]
    if provider_id == "algorithm":
        assert method == "POST"
        assert url == "https://algo.example/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer sk-algo"
    elif provider_id == "image_generation":
        assert method == "GET"
        assert url == "https://image.example/v1/models"
        assert kwargs["headers"]["Authorization"] == "Bearer sk-image"
    elif provider_id == "vision":
        assert method == "POST"
        assert url == "https://vision.example/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer sk-vision"
    elif provider_id == "football_data":
        assert method == "GET"
        assert "football-data.org/v4/competitions/PL/standings" in url
        assert kwargs["headers"]["X-Auth-Token"] == "football-token"
    elif provider_id == "grok_search":
        assert method == "POST"
        assert url == "https://grok.example/v1/web_search"
        assert kwargs["json"]["max_results"] == 1
        assert kwargs["json"]["model"] == "grok-model"
    else:
        assert method == "POST"
        assert url == "https://x-fetch.example/v1/fetch"
        assert kwargs["json"]["url"].startswith("https://x.com/")


def test_apply_atomically_replaces_only_verified_group_and_restarts(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# retained comment\n"
        "DEEPSEEK_API_URL=https://old.example/v1/chat/completions\n"
        "DEEPSEEK_MODEL=old-model\n"
        "DEEPSEEK_API_KEY=sk-chat-old\n"
        "DEEPSEEK_TEMPERATURE=0.9\n"
        "IMAGE_API_KEY=sk-image-old\n"
        "OTHER=value\n",
        encoding="utf-8",
    )

    class _Client:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            return _Response()

    monkeypatch.setattr("dashboard.api.services.provider_config_service.httpx.AsyncClient", _Client)
    service = ProviderConfigService(EnvService(str(env_file), []))
    receipt = asyncio.run(service.verify("chat", CHAT_VALUES, actor="admin"))["receipt"]
    restarts = []

    result = service.apply(
        "chat",
        CHAT_VALUES,
        receipt,
        actor="admin",
        restart=lambda: restarts.append("restart") or _RestartResult(stdout="restarted"),
    )

    text = env_file.read_text(encoding="utf-8")
    assert result["active"] is True
    assert restarts == ["restart"]
    assert "# retained comment" in text
    assert "DEEPSEEK_API_URL=https://chat.example/v1/chat/completions" in text
    assert "DEEPSEEK_MODEL=chat-model" in text
    assert "DEEPSEEK_API_KEY=sk-chat-new" in text
    assert "DEEPSEEK_TEMPERATURE=0.7" in text
    assert "IMAGE_API_KEY=sk-image-old" in text
    assert "OTHER=value" in text


def test_failed_restart_restores_previous_group_and_restarts_recovery(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original = (
        "DEEPSEEK_API_URL=https://old.example/v1/chat/completions\n"
        "DEEPSEEK_MODEL=old-model\n"
        "DEEPSEEK_API_KEY=sk-chat-old\n"
        "DEEPSEEK_TEMPERATURE=0.9\n"
        "OTHER=value\n"
    )
    env_file.write_text(original, encoding="utf-8")

    class _Client:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            return _Response()

    monkeypatch.setattr("dashboard.api.services.provider_config_service.httpx.AsyncClient", _Client)
    service = ProviderConfigService(EnvService(str(env_file), []))
    receipt = asyncio.run(service.verify("chat", CHAT_VALUES, actor="admin"))["receipt"]
    results = [_RestartResult(returncode=1, stderr="sk-should-not-leak"), _RestartResult(returncode=0, stdout="restored")]

    outcome = service.apply("chat", CHAT_VALUES, receipt, actor="admin", restart=lambda: results.pop(0))

    assert outcome == {
        "provider": "chat",
        "active": False,
        "persistence_succeeded": True,
        "initial_restart_failed": True,
        "rolled_back": True,
        "recovery_active": True,
        "recovery_restart_succeeded": True,
        "restart_error": "bot restart failed",
    }
    assert env_file.read_text(encoding="utf-8") == original


def test_failed_restart_reports_persistence_and_recovery_failure(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original = "DEEPSEEK_API_KEY=sk-chat-old\n"
    env_file.write_text(original, encoding="utf-8")

    class _Client:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            return _Response()

    monkeypatch.setattr("dashboard.api.services.provider_config_service.httpx.AsyncClient", _Client)
    service = ProviderConfigService(EnvService(str(env_file), []))
    receipt = asyncio.run(service.verify("chat", CHAT_VALUES, actor="admin"))["receipt"]
    restarts = [_RestartResult(returncode=1), _RestartResult(returncode=1)]

    outcome = service.apply("chat", CHAT_VALUES, receipt, actor="admin", restart=lambda: restarts.pop(0))

    assert outcome["persistence_succeeded"] is True
    assert outcome["initial_restart_failed"] is True
    assert outcome["recovery_restart_succeeded"] is False
    assert outcome["rolled_back"] is True
    assert env_file.read_text(encoding="utf-8") == original


def test_persistence_failure_does_not_restart_the_bot(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original = "DEEPSEEK_API_KEY=sk-chat-old\n"
    env_file.write_text(original, encoding="utf-8")

    class _Client:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            return _Response()

    monkeypatch.setattr("dashboard.api.services.provider_config_service.httpx.AsyncClient", _Client)
    env_service = EnvService(str(env_file), [])
    service = ProviderConfigService(env_service)
    receipt = asyncio.run(service.verify("chat", CHAT_VALUES, actor="admin"))["receipt"]
    monkeypatch.setattr(env_service, "replace_values_atomic", lambda values: (_ for _ in ()).throw(OSError("disk full")))
    restarts = []

    with pytest.raises(ProviderConfigError) as exc:
        service.apply("chat", CHAT_VALUES, receipt, actor="admin", restart=lambda: restarts.append(True))

    assert exc.value.code == "persistence_failed"
    assert restarts == []
    assert env_file.read_text(encoding="utf-8") == original
