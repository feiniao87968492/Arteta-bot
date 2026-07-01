import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict


DEFAULT_REMOTE_DB = "/opt/arteta_bot/arsenal_data.db"
DEFAULT_LOCAL_DB = os.path.join("data", "ecs_arsenal_data.db")
DEFAULT_STATUS_PATH = os.path.join("data", "ecs_sync_status.json")


REMOTE_SNAPSHOT_SCRIPT = """python3 - <<'PY'
import os
import sqlite3
import tempfile

source_path = {remote_db!r}
fd, snapshot_path = tempfile.mkstemp(prefix="arteta_dashboard_snapshot_", suffix=".db", dir="/tmp")
os.close(fd)
source = sqlite3.connect(source_path)
target = sqlite3.connect(snapshot_path)
try:
    source.backup(target)
finally:
    target.close()
    source.close()
print(snapshot_path)
PY"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_status(status_path: str, status: Dict[str, Any]) -> None:
    parent = os.path.dirname(os.path.abspath(status_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_path = status_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, status_path)


def _read_stream(stream) -> str:
    data = stream.read()
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data)


def _run_snapshot_command(ssh, remote_db: str) -> str:
    command = REMOTE_SNAPSHOT_SCRIPT.format(remote_db=remote_db)
    _stdin, stdout, stderr = ssh.exec_command(command)
    output = _read_stream(stdout).strip()
    error = _read_stream(stderr).strip()
    if error:
        raise RuntimeError(error)
    if not output:
        raise RuntimeError("remote snapshot command did not return a snapshot path")
    return output.splitlines()[-1].strip()


def sync_once(ssh, remote_db: str, local_db: str, status_path: str, interval_seconds: int) -> Dict[str, Any]:
    started = time.time()
    remote_snapshot = ""
    local_db_abs = os.path.abspath(local_db)
    os.makedirs(os.path.dirname(local_db_abs), exist_ok=True)
    tmp_path = local_db_abs + ".tmp"

    try:
        remote_snapshot = _run_snapshot_command(ssh, remote_db)
        sftp = ssh.open_sftp()
        try:
            sftp.get(remote_snapshot, tmp_path)
        finally:
            sftp.close()
        os.replace(tmp_path, local_db_abs)
        size = os.path.getsize(local_db_abs)
        status = {
            "ok": True,
            "last_success_at": utc_now(),
            "last_error": "",
            "remote_db": remote_db,
            "local_db": local_db_abs,
            "bytes": size,
            "duration_ms": int((time.time() - started) * 1000),
            "interval_seconds": interval_seconds,
        }
        write_status(status_path, status)
        return status
    except Exception as exc:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        status = {
            "ok": False,
            "last_success_at": "",
            "last_error": str(exc),
            "remote_db": remote_db,
            "local_db": local_db_abs,
            "bytes": os.path.getsize(local_db_abs) if os.path.exists(local_db_abs) else 0,
            "duration_ms": int((time.time() - started) * 1000),
            "interval_seconds": interval_seconds,
        }
        write_status(status_path, status)
        return status
    finally:
        if remote_snapshot:
            ssh.exec_command("rm -f " + remote_snapshot)


def _failure_status(remote_db: str, local_db: str, status_path: str, interval_seconds: int, error: str) -> Dict[str, Any]:
    local_db_abs = os.path.abspath(local_db)
    status = {
        "ok": False,
        "last_success_at": "",
        "last_error": error,
        "remote_db": remote_db,
        "local_db": local_db_abs,
        "bytes": os.path.getsize(local_db_abs) if os.path.exists(local_db_abs) else 0,
        "duration_ms": 0,
        "interval_seconds": interval_seconds,
    }
    write_status(status_path, status)
    return status


def connect_ssh(host: str, user: str, key_path: str):
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError("paramiko is required for ECS SQLite sync") from exc

    ssh_config_path = os.path.expanduser("~/.ssh/config")
    hostname = host
    username = user
    key_filename = os.path.expanduser(key_path)
    if os.path.exists(ssh_config_path):
        with open(ssh_config_path, "r", encoding="utf-8") as f:
            ssh_config = paramiko.SSHConfig()
            ssh_config.parse(f)
        host_config = ssh_config.lookup(host)
        hostname = host_config.get("hostname", hostname)
        username = host_config.get("user", username)
        identity_files = host_config.get("identityfile") or []
        if identity_files and key_path == os.path.expanduser("~/.ssh/id_ed25519"):
            key_filename = os.path.expanduser(identity_files[0])

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=hostname, username=username, key_filename=key_filename, timeout=20)
    return client


def run_sync(args) -> int:
    try:
        ssh = connect_ssh(args.host, args.user, args.key_path)
    except Exception as exc:
        _failure_status(args.remote_db, args.local_db, args.status_path, args.interval, str(exc))
        print("sync failed: {0}".format(exc), flush=True)
        return 1
    try:
        if args.once:
            status = sync_once(ssh, args.remote_db, args.local_db, args.status_path, args.interval)
            return 0 if status["ok"] else 1
        while True:
            status = sync_once(ssh, args.remote_db, args.local_db, args.status_path, args.interval)
            if status["ok"]:
                print("synced {0} bytes from {1}".format(status["bytes"], args.remote_db), flush=True)
            else:
                print("sync failed: {0}".format(status["last_error"]), flush=True)
            time.sleep(args.interval)
    finally:
        ssh.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync a consistent ECS SQLite snapshot for the Arteta dashboard.")
    parser.add_argument("--host", default="arteta")
    parser.add_argument("--user", default="root")
    parser.add_argument("--key-path", default=os.path.expanduser("~/.ssh/id_ed25519"))
    parser.add_argument("--remote-db", default=DEFAULT_REMOTE_DB)
    parser.add_argument("--local-db", default=DEFAULT_LOCAL_DB)
    parser.add_argument("--status-path", default=DEFAULT_STATUS_PATH)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> int:
    return run_sync(build_parser().parse_args())


if __name__ == "__main__":
    sys.exit(main())
