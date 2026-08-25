import json
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional


DEFAULT_DB_PATH = os.environ.get("ARTETA_DB_PATH", "arsenal_data.db")


class PendingActionStore:
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
                CREATE TABLE IF NOT EXISTS pending_agent_actions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_agent_user_group ON pending_agent_actions(user_id, group_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_agent_expires_at ON pending_agent_actions(expires_at)")
            conn.commit()
        finally:
            conn.close()

    def create_action(self, user_id: str, group_id: str, tool_name: str, arguments: Dict[str, Any], ttl_seconds: int = 300) -> str:
        now = int(time.time())
        action_id = uuid.uuid4().hex
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO pending_agent_actions
                    (id, user_id, group_id, tool_name, arguments, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    str(user_id),
                    str(group_id),
                    str(tool_name),
                    json.dumps(arguments or {}, ensure_ascii=False),
                    now,
                    now + int(ttl_seconds),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return action_id

    def _row_to_action(self, row) -> Dict[str, Any]:
        return {
            "id": row[0],
            "user_id": row[1],
            "group_id": row[2],
            "tool_name": row[3],
            "arguments": json.loads(row[4] or "{}"),
            "created_at": row[5],
            "expires_at": row[6],
        }

    def get_action(self, action_id: str) -> Optional[Dict[str, Any]]:
        now = int(time.time())
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT id, user_id, group_id, tool_name, arguments, created_at, expires_at
                FROM pending_agent_actions
                WHERE id = ? AND expires_at >= ?
                """,
                (str(action_id), now),
            ).fetchone()
            return self._row_to_action(row) if row else None
        finally:
            conn.close()

    def list_actions(self, user_id: str = "", group_id: str = "") -> List[Dict[str, Any]]:
        now = int(time.time())
        sql = """
            SELECT id, user_id, group_id, tool_name, arguments, created_at, expires_at
            FROM pending_agent_actions
            WHERE expires_at >= ?
        """
        params = [now]
        if user_id:
            sql += " AND user_id = ?"
            params.append(str(user_id))
        if group_id:
            sql += " AND group_id = ?"
            params.append(str(group_id))
        sql += " ORDER BY created_at DESC"
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_action(row) for row in rows]
        finally:
            conn.close()

    def consume_action(self, action_id: str) -> Optional[Dict[str, Any]]:
        now = int(time.time())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT id, user_id, group_id, tool_name, arguments, created_at, expires_at
                FROM pending_agent_actions
                WHERE id = ? AND expires_at >= ?
                """,
                (str(action_id), now),
            ).fetchone()
            if not row:
                conn.rollback()
                return None
            conn.execute("DELETE FROM pending_agent_actions WHERE id = ?", (str(action_id),))
            conn.commit()
            return self._row_to_action(row)
        finally:
            conn.close()

    def consume_matching_action(self, action_id: str, user_id: str, group_id: str, tool_name: str) -> Optional[Dict[str, Any]]:
        now = int(time.time())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT id, user_id, group_id, tool_name, arguments, created_at, expires_at
                FROM pending_agent_actions
                WHERE id = ?
                  AND user_id = ?
                  AND group_id = ?
                  AND tool_name = ?
                  AND expires_at >= ?
                """,
                (
                    str(action_id),
                    str(user_id),
                    str(group_id),
                    str(tool_name),
                    now,
                ),
            ).fetchone()
            if not row:
                conn.rollback()
                return None
            conn.execute("DELETE FROM pending_agent_actions WHERE id = ?", (str(action_id),))
            conn.commit()
            return self._row_to_action(row)
        finally:
            conn.close()

    def cleanup_expired_actions(self) -> int:
        now = int(time.time())
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM pending_agent_actions WHERE expires_at < ?",
                (now,),
            )
            conn.commit()
            return int(cursor.rowcount or 0)
        finally:
            conn.close()


def store_from_context(ctx) -> PendingActionStore:
    db_path = (getattr(ctx, "extra", {}) or {}).get("pending_action_db_path") or DEFAULT_DB_PATH
    return PendingActionStore(str(db_path))
