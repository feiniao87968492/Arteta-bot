import os
import sqlite3
import time
import uuid
from typing import Dict, List


DEFAULT_DB_PATH = os.environ.get("ARTETA_DB_PATH", "arsenal_data.db")


class AuditStore:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_audit_logs (
                    id TEXT PRIMARY KEY,
                    actor_user_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_audit_created_at ON agent_audit_logs(created_at)")
            conn.commit()
        finally:
            conn.close()

    def record(self, actor_user_id: str, group_id: str, tool_name: str, status: str, detail: str) -> str:
        audit_id = uuid.uuid4().hex
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO agent_audit_logs
                    (id, actor_user_id, group_id, tool_name, status, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (audit_id, str(actor_user_id), str(group_id), str(tool_name), str(status), str(detail), int(time.time())),
            )
            conn.commit()
        finally:
            conn.close()
        return audit_id

    def list_records(self, limit: int = 50) -> List[Dict[str, object]]:
        safe_limit = max(1, min(int(limit or 50), 500))
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, actor_user_id, group_id, tool_name, status, detail, created_at
                FROM agent_audit_logs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "id": row[0],
                "actor_user_id": row[1],
                "group_id": row[2],
                "tool_name": row[3],
                "status": row[4],
                "detail": row[5],
                "created_at": row[6],
            }
            for row in rows
        ]


def store_from_context(ctx) -> AuditStore:
    db_path = (getattr(ctx, "extra", {}) or {}).get("audit_db_path") or DEFAULT_DB_PATH
    return AuditStore(str(db_path))


def record_tool_audit(ctx, tool_name: str, status: str, detail: str) -> str:
    return store_from_context(ctx).record(
        actor_user_id=getattr(ctx, "user_id", ""),
        group_id=getattr(ctx, "group_id", ""),
        tool_name=tool_name,
        status=status,
        detail=detail,
    )
