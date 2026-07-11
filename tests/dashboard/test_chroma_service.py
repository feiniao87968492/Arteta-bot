import sqlite3
import sys
import types

from fastapi.testclient import TestClient

from dashboard.api.main import create_app
from dashboard.api.security import create_access_token
from dashboard.api.services.chroma_service import ChromaService


def _make_complete_pysqlite3_module():
    module = types.ModuleType("pysqlite3")
    module.connect = sqlite3.connect
    module.DatabaseError = sqlite3.DatabaseError
    module.Error = sqlite3.Error
    module.IntegrityError = sqlite3.IntegrityError
    module.NotSupportedError = sqlite3.NotSupportedError
    module.OperationalError = sqlite3.OperationalError
    module.ProgrammingError = sqlite3.ProgrammingError
    module.Row = sqlite3.Row
    module.Warning = sqlite3.Warning
    module.sqlite_version_info = sqlite3.sqlite_version_info
    return module


class FakeCollection:
    def __init__(self):
        self.deleted_ids = []

    def count(self):
        return 2

    def get(self, where=None, limit=100, include=None, ids=None):
        if ids == ["m2"]:
            return {
                "ids": ["m2"],
                "documents": ["Other group memory"],
                "metadatas": [{"group_id": "g2"}],
            }
        return {
            "ids": ["m1"],
            "documents": ["Training ground memory"],
            "metadatas": [{"group_id": "g1"}],
        }

    def query(self, query_texts, n_results=10, where=None, include=None):
        return {
            "ids": [["m1"]],
            "documents": [["Training ground memory"]],
            "metadatas": [[{"group_id": "g1"}]],
            "distances": [[0.25]],
        }

    def delete(self, ids):
        self.deleted_ids.extend(ids)


class FakeClient:
    collection = FakeCollection()

    def __init__(self, path, settings):
        self.path = path
        self.settings = settings

    def get_collection(self, name):
        return self.collection


def _install_fake_chromadb(monkeypatch):
    module = types.ModuleType("chromadb")
    module.PersistentClient = FakeClient
    config_module = types.ModuleType("chromadb.config")

    class Settings:
        def __init__(self, anonymized_telemetry=False):
            self.anonymized_telemetry = anonymized_telemetry

    config_module.Settings = Settings
    monkeypatch.setitem(sys.modules, "chromadb", module)
    monkeypatch.setitem(sys.modules, "chromadb.config", config_module)
    FakeClient.collection = FakeCollection()


def _auth_headers(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SECRET_KEY", "unit-test-secret")
    token = create_access_token({"sub": "admin"})
    return {"Authorization": "Bearer " + token}


def _make_db(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE players (user_id TEXT, group_id TEXT, nickname TEXT, level TEXT, favorability INTEGER, last_seen TEXT, profile_json TEXT)")
    conn.execute("INSERT INTO players VALUES (?, ?, ?, ?, ?, ?, ?)", ("u1", "g1", "Saka", "核心首发", 230, "2026-05-22", "{}"))
    conn.commit()
    conn.close()


def _client_with_memory(monkeypatch, tmp_path, protected=False):
    chroma_dir = tmp_path / "chroma_db"
    chroma_dir.mkdir()
    db_path = tmp_path / "arsenal_data.db"
    _make_db(db_path)
    _install_fake_chromadb(monkeypatch)
    monkeypatch.setenv("ARTETA_CHROMA_DIR", str(chroma_dir))
    monkeypatch.setenv("ARTETA_DB_PATH", str(db_path))
    monkeypatch.setenv("DASHBOARD_READONLY", "false")
    monkeypatch.setattr("dashboard.api.config.REPO_ROOT", str(tmp_path))
    if protected:
        from dashboard.api.services.sqlite_service import SQLiteService

        SQLiteService(str(db_path)).set_group_password("g1", "team-secret")
    return TestClient(create_app()), _auth_headers(monkeypatch)


def test_service_import_and_health_do_not_require_chromadb(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "chromadb", None)
    service = ChromaService(str(tmp_path / "missing-chroma"))

    health = service.health()

    assert health["available"] is False
    assert health["collection"] == "group_memories"
    assert health["count"] == 0


def test_service_installs_pysqlite3_before_importing_chromadb(tmp_path, monkeypatch):
    chroma_dir = tmp_path / "chroma_db"
    chroma_dir.mkdir()
    pysqlite3_module = _make_complete_pysqlite3_module()
    monkeypatch.setitem(sys.modules, "pysqlite3", pysqlite3_module)
    monkeypatch.setitem(sys.modules, "sqlite3", sqlite3)
    sys.modules.pop("chromadb", None)
    sys.modules.pop("chromadb.config", None)

    imported_sqlite = []
    module = types.ModuleType("chromadb")

    class ImportCheckingClient(FakeClient):
        def __init__(self, path, settings):
            imported_sqlite.append(sys.modules.get("sqlite3"))
            super().__init__(path, settings)

    module.PersistentClient = ImportCheckingClient
    config_module = types.ModuleType("chromadb.config")

    class Settings:
        def __init__(self, anonymized_telemetry=False):
            self.anonymized_telemetry = anonymized_telemetry

    config_module.Settings = Settings
    monkeypatch.setitem(sys.modules, "chromadb", module)
    monkeypatch.setitem(sys.modules, "chromadb.config", config_module)

    service = ChromaService(str(chroma_dir))
    service.health()

    assert imported_sqlite == [pysqlite3_module]


def test_service_skips_incomplete_pysqlite3_module(tmp_path, monkeypatch):
    chroma_dir = tmp_path / "chroma_db"
    chroma_dir.mkdir()
    incomplete_pysqlite3 = types.ModuleType("pysqlite3")
    original_sqlite = sys.modules.get("sqlite3")
    monkeypatch.setitem(sys.modules, "pysqlite3", incomplete_pysqlite3)
    monkeypatch.setitem(sys.modules, "sqlite3", sqlite3)
    sys.modules.pop("chromadb", None)
    sys.modules.pop("chromadb.config", None)

    imported_sqlite = []
    module = types.ModuleType("chromadb")

    class ImportCheckingClient(FakeClient):
        def __init__(self, path, settings):
            imported_sqlite.append(sys.modules.get("sqlite3"))
            super().__init__(path, settings)

    module.PersistentClient = ImportCheckingClient
    config_module = types.ModuleType("chromadb.config")

    class Settings:
        def __init__(self, anonymized_telemetry=False):
            self.anonymized_telemetry = anonymized_telemetry

    config_module.Settings = Settings
    monkeypatch.setitem(sys.modules, "chromadb", module)
    monkeypatch.setitem(sys.modules, "chromadb.config", config_module)

    service = ChromaService(str(chroma_dir))
    service.health()

    assert imported_sqlite == [sqlite3]


def test_service_lists_queries_and_deletes_with_lazy_chromadb(tmp_path, monkeypatch):
    chroma_dir = tmp_path / "chroma_db"
    chroma_dir.mkdir()
    _install_fake_chromadb(monkeypatch)
    service = ChromaService(str(chroma_dir))

    assert service.health()["count"] == 2
    assert service.list_memories("g1", 10)[0]["preview"] == "Training ground memory"
    assert service.query("g1", "training", 5)[0]["distance"] == 0.25
    assert service.delete(["m1"]) == 1
    assert FakeClient.collection.deleted_ids == ["m1"]


def test_memory_endpoints_require_group_id(tmp_path, monkeypatch):
    client, headers = _client_with_memory(monkeypatch, tmp_path)

    list_response = client.get("/api/memories", headers=headers)
    search_response = client.get("/api/memories/search?q=training", headers=headers)

    assert list_response.status_code == 400
    assert search_response.status_code == 400


def test_protected_group_memory_requires_password(tmp_path, monkeypatch):
    client, headers = _client_with_memory(monkeypatch, tmp_path, protected=True)

    missing_response = client.get("/api/memories?group_id=g1", headers=headers)
    wrong_response = client.get("/api/memories?group_id=g1", headers={**headers, "X-Group-Password": "wrong"})
    ok_response = client.get("/api/memories?group_id=g1", headers={**headers, "X-Group-Password": "team-secret"})

    assert missing_response.status_code == 403
    assert wrong_response.status_code == 403
    assert ok_response.status_code == 200
    assert ok_response.json()["data"][0]["metadata"]["group_id"] == "g1"


def test_protected_group_delete_requires_password_and_matching_group(tmp_path, monkeypatch):
    client, headers = _client_with_memory(monkeypatch, tmp_path, protected=True)

    missing_response = client.post("/api/memories/delete", json={"group_id": "g1", "ids": ["m1"]}, headers=headers)
    wrong_group_response = client.post(
        "/api/memories/delete",
        json={"group_id": "g1", "ids": ["m2"], "password": "team-secret"},
        headers=headers,
    )
    ok_response = client.post(
        "/api/memories/delete",
        json={"group_id": "g1", "ids": ["m1"], "password": "team-secret"},
        headers=headers,
    )

    assert missing_response.status_code == 403
    assert wrong_group_response.status_code == 400
    assert ok_response.status_code == 200
    assert FakeClient.collection.deleted_ids == ["m1"]


def test_delete_endpoint_respects_readonly_without_deleting(tmp_path, monkeypatch):
    chroma_dir = tmp_path / "chroma_db"
    chroma_dir.mkdir()
    db_path = tmp_path / "arsenal_data.db"
    _make_db(db_path)
    _install_fake_chromadb(monkeypatch)
    monkeypatch.setenv("ARTETA_CHROMA_DIR", str(chroma_dir))
    monkeypatch.setenv("ARTETA_DB_PATH", str(db_path))
    monkeypatch.setenv("DASHBOARD_READONLY", "true")
    client = TestClient(create_app())

    response = client.post("/api/memories/delete", json={"group_id": "g1", "ids": ["m1"]}, headers=_auth_headers(monkeypatch))

    assert response.status_code == 403
    assert FakeClient.collection.deleted_ids == []


def test_delete_endpoint_audits_successful_delete(tmp_path, monkeypatch):
    chroma_dir = tmp_path / "chroma_db"
    chroma_dir.mkdir()
    audit_log = tmp_path / "logs" / "dashboard_audit.log"
    _install_fake_chromadb(monkeypatch)
    monkeypatch.setenv("ARTETA_CHROMA_DIR", str(chroma_dir))
    monkeypatch.setenv("DASHBOARD_READONLY", "false")
    monkeypatch.setattr("dashboard.api.config.REPO_ROOT", str(tmp_path))
    client = TestClient(create_app())

    db_path = tmp_path / "arsenal_data.db"
    _make_db(db_path)
    monkeypatch.setenv("ARTETA_DB_PATH", str(db_path))

    response = client.post("/api/memories/delete", json={"group_id": "g1", "ids": ["m1"]}, headers=_auth_headers(monkeypatch))

    assert response.status_code == 200
    assert response.json()["data"]["deleted"] == 1
    assert FakeClient.collection.deleted_ids == ["m1"]
    audit_text = audit_log.read_text(encoding="utf-8")
    assert "action=memory.delete" in audit_text
    assert "target=g1/m1" in audit_text
    assert "result=ok" in audit_text
