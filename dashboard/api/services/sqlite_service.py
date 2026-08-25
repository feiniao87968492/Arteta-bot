import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, List, Optional


FAVOR_LEVEL_THRESHOLDS = [
    ("看台内鬼", -50),
    ("预备队", 0),
    ("青训生", 50),
    ("一线队", 200),
    ("核心首发", 500),
    ("传奇队长", math.inf),
]


def _level_for_favor(favor: int) -> str:
    for level, threshold in FAVOR_LEVEL_THRESHOLDS:
        if favor < threshold:
            return level
    return FAVOR_LEVEL_THRESHOLDS[-1][0]


class SQLiteService:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def is_available(self) -> bool:
        return os.path.exists(self.db_path)

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _table_exists(self, conn, name: str) -> bool:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()
        return row is not None

    def _ensure_group_settings_table(self, conn) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboard_group_settings (
                group_id TEXT PRIMARY KEY,
                password_salt TEXT,
                password_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    def _ensure_group_names_table(self, conn) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboard_group_names (
                group_id TEXT PRIMARY KEY,
                group_name TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    def _hash_password(self, password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200000).hex()

    def _settings_from_row(self, group_id: str, row) -> Dict[str, Any]:
        enabled = bool(row and row["password_hash"])
        return {"group_id": group_id, "memory_password_enabled": enabled}

    def _group_names(self, conn) -> Dict[str, str]:
        if not self._table_exists(conn, "dashboard_group_names"):
            return {}
        rows = conn.execute("SELECT group_id, group_name FROM dashboard_group_names").fetchall()
        return {row["group_id"]: row["group_name"] for row in rows}

    def _group_user_sources(self, conn, filtered: bool = False) -> List[str]:
        suffix = " WHERE group_id = ?" if filtered else ""
        sources = []
        if self._table_exists(conn, "players"):
            sources.append("SELECT group_id, user_id, nickname FROM players" + suffix)
        if self._table_exists(conn, "messages"):
            sources.append("SELECT group_id, user_id, NULL AS nickname FROM messages" + suffix)
        if self._table_exists(conn, "daily_messages"):
            sources.append("SELECT group_id, user_id, nickname FROM daily_messages" + suffix)
        if self._table_exists(conn, "nicknames"):
            sources.append("SELECT group_id, user_id, nickname FROM nicknames" + suffix)
        if self._table_exists(conn, "member_relations"):
            sources.append("SELECT group_id, user_id, NULL AS nickname FROM member_relations" + suffix)
            sources.append("SELECT group_id, target_user_id AS user_id, NULL AS nickname FROM member_relations" + suffix)
        return sources

    def _message_summary_cte(self, conn) -> str:
        parts = []
        if self._table_exists(conn, "messages"):
            parts.append("SELECT group_id, user_id, message, timestamp FROM messages")
        if self._table_exists(conn, "daily_messages"):
            parts.append("SELECT group_id, user_id, message, timestamp FROM daily_messages")
        if not parts:
            return "SELECT NULL AS group_id, NULL AS user_id, NULL AS message, NULL AS timestamp WHERE 0"
        return "\n                    UNION ALL\n                    ".join(parts)

    def list_groups(self) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []
        with self._connect() as conn:
            sources = self._group_user_sources(conn)
            if not sources:
                return []
            rows = conn.execute(
                """
                WITH group_users AS (
                    {}
                ), all_messages AS (
                    {}
                ), group_messages AS (
                    SELECT group_id, COUNT(message) AS message_count, MAX(timestamp) AS last_message_at
                    FROM all_messages
                    GROUP BY group_id
                ), group_players AS (
                    SELECT group_id, MAX(last_seen) AS last_seen_at
                    FROM players
                    GROUP BY group_id
                )
                SELECT gu.group_id,
                       COUNT(DISTINCT gu.user_id) AS user_count,
                       COALESCE(gm.message_count, 0) AS message_count,
                       MAX(COALESCE(gm.last_message_at, gp.last_seen_at)) AS last_activity
                FROM group_users gu
                LEFT JOIN group_messages gm ON gu.group_id = gm.group_id
                LEFT JOIN group_players gp ON gu.group_id = gp.group_id
                GROUP BY gu.group_id, gm.message_count, gm.last_message_at, gp.last_seen_at
                ORDER BY last_activity DESC
                """.format(
                    "\n                    UNION\n                    ".join(sources),
                    self._message_summary_cte(conn),
                )
            ).fetchall()
        settings_by_group = {}
        group_names = {}
        with self._connect() as conn:
            if self._table_exists(conn, "dashboard_group_settings"):
                settings_rows = conn.execute("SELECT group_id, password_hash FROM dashboard_group_settings").fetchall()
                settings_by_group = {row["group_id"]: bool(row["password_hash"]) for row in settings_rows}
            group_names = self._group_names(conn)
        result = []
        for row in rows:
            item = dict(row)
            item["group_name"] = group_names.get(item["group_id"], "")
            item["memory_password_enabled"] = settings_by_group.get(item["group_id"], False)
            result.append(item)
        return result

    def list_users(self, group_id: str) -> List[Dict[str, Any]]:
        if not self.is_available():
            return []
        with self._connect() as conn:
            sources = self._group_user_sources(conn, filtered=True)
            if not sources:
                return []
            rows = conn.execute(
                """
                WITH group_users AS (
                    {}
                ), all_messages AS (
                    {}
                )
                SELECT gu.user_id,
                       gu.group_id,
                       COALESCE(p.nickname, MAX(gu.nickname), gu.user_id) AS nickname,
                       COALESCE(p.level, '') AS level,
                       COALESCE(p.favorability, 0) AS favorability,
                       p.last_seen,
                       COUNT(am.message) AS message_count
                FROM group_users gu
                LEFT JOIN players p ON gu.group_id = p.group_id AND gu.user_id = p.user_id
                LEFT JOIN all_messages am ON gu.group_id = am.group_id AND gu.user_id = am.user_id
                GROUP BY gu.user_id, gu.group_id, p.nickname, p.level, p.favorability, p.last_seen
                ORDER BY p.favorability DESC, message_count DESC
                """.format(
                    "\n                    UNION\n                    ".join(sources),
                    self._message_summary_cte(conn),
                ),
                tuple(group_id for _ in sources),
            ).fetchall()
        return [dict(row) for row in rows]

    def _latest_profile_update(self, conn, group_id: str, user_id: str) -> Dict[str, Any]:
        if not self._table_exists(conn, "profile_updates"):
            return {}
        row = conn.execute(
            "SELECT new_profile FROM profile_updates WHERE group_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT 1",
            (group_id, user_id),
        ).fetchone()
        if not row or not row[0]:
            return {}
        try:
            return json.loads(row[0])
        except ValueError:
            return {"raw": row[0]}

    def get_user_detail(self, group_id: str, user_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            user = conn.execute(
                "SELECT * FROM players WHERE group_id = ? AND user_id = ?",
                (group_id, user_id),
            ).fetchone()
            nicknames = conn.execute(
                "SELECT nickname, first_seen, last_seen FROM nicknames WHERE group_id = ? AND user_id = ? ORDER BY last_seen DESC LIMIT 10",
                (group_id, user_id),
            ).fetchall()
            messages = conn.execute(
                """
                WITH all_messages AS (
                    {}
                )
                SELECT message, timestamp FROM all_messages
                WHERE group_id = ? AND user_id = ?
                ORDER BY timestamp DESC LIMIT 20
                """.format(self._message_summary_cte(conn)),
                (group_id, user_id),
            ).fetchall()
            message_count = conn.execute(
                """
                WITH all_messages AS (
                    {}
                )
                SELECT COUNT(*) FROM all_messages WHERE group_id = ? AND user_id = ?
                """.format(self._message_summary_cte(conn)),
                (group_id, user_id),
            ).fetchone()
            relations = []
            if self._table_exists(conn, "member_relations"):
                relations = conn.execute(
                    "SELECT target_user_id, interaction_count, last_interaction_time FROM member_relations WHERE group_id = ? AND user_id = ? ORDER BY interaction_count DESC LIMIT 20",
                    (group_id, user_id),
                ).fetchall()
            user_dict = dict(user) if user else None
            personality_profile = {}
            if user_dict and user_dict.get("profile_json"):
                try:
                    personality_profile = json.loads(user_dict["profile_json"])
                except ValueError:
                    personality_profile = {"raw": user_dict["profile_json"]}
            if not personality_profile:
                personality_profile = self._latest_profile_update(conn, group_id, user_id)
        detail = {
            "user_id": user_id,
            "current_nickname": user_dict.get("nickname", "") if user_dict else "",
            "level": user_dict.get("level", "") if user_dict else "",
            "favorability": user_dict.get("favorability", 0) if user_dict else 0,
            "last_seen": user_dict.get("last_seen", 0) if user_dict else 0,
            "nicknames": [dict(row) for row in nicknames],
            "recent_messages": [dict(row) for row in messages],
            "message_count": message_count[0] if message_count else 0,
            "personality_profile": personality_profile,
            "relations": [dict(row) for row in relations],
        }
        detail["user"] = user_dict
        detail["profile"] = personality_profile
        detail["messages"] = detail["recent_messages"]
        return detail

    def get_group_settings(self, group_id: str) -> Dict[str, Any]:
        if not self.is_available():
            return {"group_id": group_id, "memory_password_enabled": False}
        with self._connect() as conn:
            if not self._table_exists(conn, "dashboard_group_settings"):
                return {"group_id": group_id, "memory_password_enabled": False}
            row = conn.execute(
                "SELECT group_id, password_hash FROM dashboard_group_settings WHERE group_id = ?",
                (group_id,),
            ).fetchone()
        return self._settings_from_row(group_id, row)

    def upsert_group_name(self, group_id: str, group_name: str) -> Dict[str, str]:
        clean_group_id = group_id.strip()
        clean_group_name = group_name.strip()
        if not clean_group_id or not clean_group_name or not self.is_available():
            return {"group_id": clean_group_id, "group_name": clean_group_name}
        now = datetime.utcnow().isoformat(timespec="seconds")
        with self._connect() as conn:
            self._ensure_group_names_table(conn)
            conn.execute(
                """
                INSERT INTO dashboard_group_names (group_id, group_name, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(group_id) DO UPDATE SET group_name = excluded.group_name, updated_at = excluded.updated_at
                """,
                (clean_group_id, clean_group_name, now),
            )
            conn.commit()
        return {"group_id": clean_group_id, "group_name": clean_group_name}

    def set_group_password(self, group_id: str, password: str) -> Dict[str, Any]:
        salt = secrets.token_hex(16)
        password_hash = self._hash_password(password, salt)
        now = datetime.utcnow().isoformat(timespec="seconds")
        with self._connect() as conn:
            self._ensure_group_settings_table(conn)
            existing = conn.execute(
                "SELECT group_id FROM dashboard_group_settings WHERE group_id = ?",
                (group_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE dashboard_group_settings SET password_salt = ?, password_hash = ?, updated_at = ? WHERE group_id = ?",
                    (salt, password_hash, now, group_id),
                )
            else:
                conn.execute(
                    "INSERT INTO dashboard_group_settings (group_id, password_salt, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (group_id, salt, password_hash, now, now),
                )
            conn.commit()
        return self.get_group_settings(group_id)

    def clear_group_password(self, group_id: str) -> Dict[str, Any]:
        if not self.is_available():
            return {"group_id": group_id, "memory_password_enabled": False}
        with self._connect() as conn:
            self._ensure_group_settings_table(conn)
            conn.execute("DELETE FROM dashboard_group_settings WHERE group_id = ?", (group_id,))
            conn.commit()
        return self.get_group_settings(group_id)

    def group_requires_password(self, group_id: str) -> bool:
        return bool(self.get_group_settings(group_id)["memory_password_enabled"])

    def verify_group_password(self, group_id: str, password: str) -> bool:
        if not password or not self.is_available():
            return False
        with self._connect() as conn:
            if not self._table_exists(conn, "dashboard_group_settings"):
                return False
            row = conn.execute(
                "SELECT password_salt, password_hash FROM dashboard_group_settings WHERE group_id = ?",
                (group_id,),
            ).fetchone()
        if not row or not row["password_hash"] or not row["password_salt"]:
            return False
        candidate = self._hash_password(password, row["password_salt"])
        return hmac.compare_digest(candidate, row["password_hash"])

    def update_user_profile(self, group_id: str, user_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
        serialized = json.dumps(profile, ensure_ascii=False)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT user_id FROM players WHERE group_id = ? AND user_id = ?",
                (group_id, user_id),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE players SET profile_json = ? WHERE group_id = ? AND user_id = ?",
                    (serialized, group_id, user_id),
                )
            else:
                conn.execute(
                    "INSERT INTO players (user_id, group_id, nickname, level, favorability, last_seen, profile_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, group_id, user_id, "青训生", 0, 0, serialized),
                )
            conn.commit()
        return self.get_user_detail(group_id, user_id)

    def update_user_favor(
        self,
        group_id: str,
        user_id: str,
        *,
        favor: Optional[int] = None,
        delta: Optional[int] = None,
        nickname: Optional[str] = None,
    ) -> Dict[str, Any]:
        if (favor is None) == (delta is None):
            raise ValueError("update_user_favor requires exactly one of favor or delta")
        now = int(time.time())
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT favorability, nickname FROM players WHERE group_id = ? AND user_id = ?",
                (group_id, user_id),
            ).fetchone()
            if existing:
                current = int(existing["favorability"] or 0)
                resolved_nickname = nickname or (existing["nickname"] or user_id)
                new_favor = int(favor) if favor is not None else current + int(delta or 0)
                new_level = _level_for_favor(new_favor)
                conn.execute(
                    "UPDATE players SET favorability = ?, level = ?, nickname = ?, last_seen = ? WHERE group_id = ? AND user_id = ?",
                    (new_favor, new_level, resolved_nickname, now, group_id, user_id),
                )
            else:
                resolved_nickname = nickname or user_id
                new_favor = int(favor) if favor is not None else int(delta or 0)
                new_level = _level_for_favor(new_favor)
                conn.execute(
                    "INSERT INTO players (user_id, group_id, nickname, favorability, level, last_seen) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, group_id, resolved_nickname, new_favor, new_level, now),
                )
            conn.commit()
        return self.get_user_detail(group_id, user_id)

    def delete_user_profile(self, group_id: str, user_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                "UPDATE players SET profile_json = ? WHERE group_id = ? AND user_id = ?",
                ("{}", group_id, user_id),
            )
            conn.commit()
        return self.get_user_detail(group_id, user_id)
