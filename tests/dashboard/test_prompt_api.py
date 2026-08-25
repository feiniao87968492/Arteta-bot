from fastapi.testclient import TestClient

from dashboard.api.main import create_app


def _client(monkeypatch, tmp_path, readonly=False):
    monkeypatch.setenv("ARTETA_PROMPTS_FILE", str(tmp_path / "prompts.json"))
    monkeypatch.setenv("DASHBOARD_READONLY", "true" if readonly else "false")
    monkeypatch.setenv("DASHBOARD_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DASHBOARD_WEB_DIST", str(tmp_path / "dist"))
    return TestClient(create_app())


def test_prompt_api_lists_builtin_entries(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.get("/api/prompts")

    assert response.status_code == 200
    data = response.json()["data"]
    assert any(entry["key"] == "arteta.main" for entry in data)


def test_prompt_api_updates_builtin_entry(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.put("/api/prompts/arteta.main", json={"content": "新的主教练", "enabled": True})

    assert response.status_code == 200
    assert response.json()["data"]["content"] == "新的主教练"


def test_prompt_api_creates_and_deletes_custom_entry(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    create_response = client.post("/api/prompts", json={
        "key": "custom.note",
        "title": "自定义提醒",
        "category": "自定义",
        "content": "保持紧凑。",
        "variables": [],
        "enabled": True,
    })
    delete_response = client.delete("/api/prompts/custom.note")

    assert create_response.status_code == 200
    assert delete_response.status_code == 200


def test_prompt_api_rejects_builtin_delete(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.delete("/api/prompts/arteta.main")

    assert response.status_code == 400
    assert "built-in" in response.json()["error"]["message"]


def test_prompt_api_blocks_writes_in_readonly(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, readonly=True)

    response = client.put("/api/prompts/arteta.main", json={"content": "readonly", "enabled": True})

    assert response.status_code == 403
