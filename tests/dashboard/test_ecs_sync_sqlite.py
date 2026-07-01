import importlib.util
import json
import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
SCRIPT_PATH = os.path.join(REPO_ROOT, "tools", "sync_ecs_sqlite.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("sync_ecs_sqlite", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeSFTP:
    def __init__(self, content=b"snapshot"):
        self.content = content
        self.downloads = []
        self.closed = False

    def get(self, remote_path, local_path):
        self.downloads.append((remote_path, local_path))
        with open(local_path, "wb") as f:
            f.write(self.content)

    def close(self):
        self.closed = True


class FakeSSH:
    def __init__(self, sftp=None, snapshot="/tmp/arteta_dashboard_snapshot_123.db", exec_error=""):
        self.snapshot = snapshot
        self.exec_error = exec_error
        self.sftp = sftp or FakeSFTP()
        self.commands = []
        self.removed = []
        self.closed = False

    def exec_command(self, command):
        self.commands.append(command)
        if command.startswith("rm -f "):
            self.removed.append(command)
        return None, FakeStream(self.snapshot + "\n"), FakeStream(self.exec_error)

    def open_sftp(self):
        return self.sftp

    def close(self):
        self.closed = True


class FakeStream:
    def __init__(self, text):
        self.text = text

    def read(self):
        return self.text.encode("utf-8")


def test_sync_once_downloads_snapshot_atomically_and_writes_status(tmp_path):
    module = _load_module()
    local_db = tmp_path / "ecs_arsenal_data.db"
    status_path = tmp_path / "ecs_sync_status.json"
    ssh = FakeSSH()

    result = module.sync_once(
        ssh=ssh,
        remote_db="/opt/arteta_bot/arsenal_data.db",
        local_db=str(local_db),
        status_path=str(status_path),
        interval_seconds=10,
    )

    assert result["ok"] is True
    assert local_db.read_bytes() == b"snapshot"
    assert not os.path.exists(str(local_db) + ".tmp")
    assert ssh.sftp.downloads == [("/tmp/arteta_dashboard_snapshot_123.db", str(local_db) + ".tmp")]
    assert ssh.removed == ["rm -f /tmp/arteta_dashboard_snapshot_123.db"]

    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["last_error"] == ""
    assert status["remote_db"] == "/opt/arteta_bot/arsenal_data.db"
    assert status["local_db"] == str(local_db)
    assert status["bytes"] == len(b"snapshot")
    assert status["interval_seconds"] == 10
    assert status["last_success_at"]


def test_sync_once_keeps_existing_db_when_snapshot_command_fails(tmp_path):
    module = _load_module()
    local_db = tmp_path / "ecs_arsenal_data.db"
    status_path = tmp_path / "ecs_sync_status.json"
    local_db.write_bytes(b"old-db")
    ssh = FakeSSH(snapshot="", exec_error="boom")

    result = module.sync_once(
        ssh=ssh,
        remote_db="/opt/arteta_bot/arsenal_data.db",
        local_db=str(local_db),
        status_path=str(status_path),
        interval_seconds=10,
    )

    assert result["ok"] is False
    assert local_db.read_bytes() == b"old-db"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["last_success_at"] == ""
    assert "boom" in status["last_error"]
