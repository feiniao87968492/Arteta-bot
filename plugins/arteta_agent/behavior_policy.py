import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Set


POLICY_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-zA-Z0-9_]+)+$")
ALLOWED_PREFIXES = (
    "emoji.",
    "progress.",
    "render.",
    "reply.",
    "trace.",
    "tool.",
    "route.",
)
FORBIDDEN_KEY_PARTS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "cookie",
    "password",
    "permission",
    "admin",
)

CHINESE_NUMBERS = {
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _policy_path() -> Path:
    configured = os.environ.get("ARTETA_AGENT_BEHAVIOR_POLICY_PATH")
    if configured:
        return Path(configured)
    # Compatibility for tests and deployments that already configured one of
    # the older single-purpose policy files. New installs use the unified path.
    legacy_ui = os.environ.get("ARTETA_AGENT_UI_PREFS_PATH")
    if legacy_ui:
        return Path(legacy_ui)
    legacy_tool = os.environ.get("ARTETA_AGENT_TOOL_POLICY_PATH")
    if legacy_tool:
        return Path(legacy_tool)
    return Path(os.getcwd()) / "config" / "agent_behavior_policy.json"


def _empty_policy() -> Dict[str, Any]:
    return {"groups": {}}


def _load_policy() -> Dict[str, Any]:
    path = _policy_path()
    if not path.exists():
        return _empty_policy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_policy()
    if not isinstance(data, dict):
        return _empty_policy()
    data.setdefault("groups", {})
    return data


def _save_policy(data: Dict[str, Any]) -> None:
    path = _policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _sqlite_path() -> Path:
    configured = os.environ.get("ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH")
    if configured:
        return Path(configured)
    return Path("")


def _use_sqlite_store() -> bool:
    return bool(os.environ.get("ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH"))


def _connect_sqlite():
    path = _sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS behavior_policies (
            group_id TEXT NOT NULL,
            policy_key TEXT NOT NULL,
            value_json TEXT NOT NULL,
            mode TEXT NOT NULL,
            reason TEXT NOT NULL,
            source TEXT NOT NULL,
            remaining_turns INTEGER NULL,
            PRIMARY KEY (group_id, policy_key)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS behavior_phrase_styles (
            group_id TEXT NOT NULL,
            phrase TEXT NOT NULL,
            value_json TEXT NOT NULL,
            PRIMARY KEY (group_id, phrase)
        )
        """
    )
    return conn


def _sqlite_has_data(conn) -> bool:
    policy_count = conn.execute("SELECT COUNT(*) FROM behavior_policies").fetchone()[0]
    phrase_count = conn.execute("SELECT COUNT(*) FROM behavior_phrase_styles").fetchone()[0]
    return bool(policy_count or phrase_count)


def _backup_legacy_policy_file(path: Path) -> None:
    backup = path.with_name(path.name + ".bak")
    if not backup.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def _migrate_json_to_sqlite_if_needed(conn) -> None:
    path = _policy_path()
    if not path.exists() or _sqlite_has_data(conn):
        return
    data = _load_policy()
    groups = data.get("groups", {})
    if not isinstance(groups, dict):
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        if _sqlite_has_data(conn):
            conn.execute("COMMIT")
            return
        for group_id, group in groups.items():
            if not isinstance(group, dict):
                continue
            policies = group.get("policies", {})
            if isinstance(policies, dict):
                for key, item in policies.items():
                    if not isinstance(item, dict):
                        continue
                    value_json = json.dumps(item.get("value"), ensure_ascii=False, sort_keys=True)
                    remaining = item.get("ttl_turns")
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO behavior_policies
                        (group_id, policy_key, value_json, mode, reason, source, remaining_turns)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            _group_id(group_id),
                            str(key),
                            value_json,
                            str(item.get("mode") or "soft"),
                            str(item.get("reason") or ""),
                            str(item.get("source") or "agent"),
                            int(remaining) if remaining is not None else None,
                        ),
                    )
            phrase_styles = group.get("phrase_styles", [])
            if isinstance(phrase_styles, list):
                for rule in phrase_styles:
                    if not isinstance(rule, dict) or not rule.get("phrase"):
                        continue
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO behavior_phrase_styles
                        (group_id, phrase, value_json)
                        VALUES (?, ?, ?)
                        """,
                        (
                            _group_id(group_id),
                            str(rule.get("phrase")),
                            json.dumps(rule, ensure_ascii=False, sort_keys=True),
                        ),
                    )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    _backup_legacy_policy_file(path)


def _with_sqlite():
    conn = _connect_sqlite()
    _migrate_json_to_sqlite_if_needed(conn)
    return conn


def _policy_item_from_sqlite_row(row) -> Dict[str, Any]:
    if not row:
        return {}
    key, value_json, mode, reason, source, remaining_turns = row
    try:
        value = json.loads(value_json)
    except Exception:
        value = None
    item = {
        "key": str(key),
        "value": value,
        "mode": str(mode or "soft"),
        "reason": str(reason or ""),
        "source": str(source or "agent"),
    }
    if remaining_turns is not None:
        item["ttl_turns"] = int(remaining_turns)
    return item


def _group_id(group_id: str) -> str:
    return str(group_id or "global")


def validate_policy_key(key: str) -> str:
    value = str(key or "").strip()
    if not value:
        raise ValueError("policy key is required")
    if not POLICY_KEY_RE.match(value):
        raise ValueError("unsupported behavior policy key: {0}".format(key))
    lowered = value.lower()
    if not lowered.startswith(ALLOWED_PREFIXES):
        raise ValueError("unsupported behavior policy prefix: {0}".format(key))
    if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
        raise ValueError("unsafe behavior policy key: {0}".format(key))
    return value


def _normalize_mode(mode: str) -> str:
    value = str(mode or "soft").strip().lower()
    if value not in ("soft", "hard"):
        raise ValueError("unsupported behavior policy mode: {0}".format(mode))
    return value


def _normalize_ttl(ttl_turns) -> int:
    if ttl_turns in (None, "", 0):
        return 0
    return max(1, min(int(ttl_turns), 100))


def set_group_policy(
    group_id: str,
    key: str,
    value: Any,
    mode: str = "soft",
    ttl_turns=None,
    reason: str = "",
    source: str = "agent",
) -> Dict[str, Any]:
    safe_key = validate_policy_key(key)
    ttl = _normalize_ttl(ttl_turns)
    item = {
        "key": safe_key,
        "value": value,
        "mode": _normalize_mode(mode),
        "reason": str(reason or ""),
        "source": str(source or "agent"),
    }
    if ttl:
        item["ttl_turns"] = ttl

    if _use_sqlite_store():
        conn = _with_sqlite()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT OR REPLACE INTO behavior_policies
                (group_id, policy_key, value_json, mode, reason, source, remaining_turns)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _group_id(group_id),
                    safe_key,
                    json.dumps(value, ensure_ascii=False, sort_keys=True),
                    item["mode"],
                    item["reason"],
                    item["source"],
                    ttl if ttl else None,
                ),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        return dict(item)

    data = _load_policy()
    group = data.setdefault("groups", {}).setdefault(_group_id(group_id), {})
    group.setdefault("policies", {})[safe_key] = item
    _save_policy(data)
    return dict(item)


def get_group_policy(group_id: str, key: str) -> Dict[str, Any]:
    if _use_sqlite_store():
        conn = _with_sqlite()
        try:
            row = conn.execute(
                """
                SELECT policy_key, value_json, mode, reason, source, remaining_turns
                FROM behavior_policies
                WHERE group_id=? AND policy_key=? AND (remaining_turns IS NULL OR remaining_turns > 0)
                """,
                (_group_id(group_id), str(key or "")),
            ).fetchone()
            return _policy_item_from_sqlite_row(row)
        finally:
            conn.close()

    data = _load_policy()
    item = (
        data.get("groups", {})
        .get(_group_id(group_id), {})
        .get("policies", {})
        .get(str(key or ""), {})
    )
    if not isinstance(item, dict):
        return {}
    if int(item.get("ttl_turns") or 1) <= 0:
        return {}
    return dict(item)


def list_group_policies(group_id: str) -> Dict[str, Dict[str, Any]]:
    if _use_sqlite_store():
        conn = _with_sqlite()
        try:
            rows = conn.execute(
                """
                SELECT policy_key, value_json, mode, reason, source, remaining_turns
                FROM behavior_policies
                WHERE group_id=? AND (remaining_turns IS NULL OR remaining_turns > 0)
                ORDER BY policy_key
                """,
                (_group_id(group_id),),
            ).fetchall()
            result = {}
            for row in rows:
                item = _policy_item_from_sqlite_row(row)
                if item:
                    result[item["key"]] = item
            return result
        finally:
            conn.close()

    data = _load_policy()
    policies = data.get("groups", {}).get(_group_id(group_id), {}).get("policies", {})
    if not isinstance(policies, dict):
        return {}
    result = {}
    for key, item in policies.items():
        if isinstance(item, dict) and int(item.get("ttl_turns") or 1) > 0:
            result[str(key)] = dict(item)
    return result


def delete_group_policy(group_id: str, key: str) -> bool:
    if _use_sqlite_store():
        conn = _with_sqlite()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "DELETE FROM behavior_policies WHERE group_id=? AND policy_key=?",
                (_group_id(group_id), str(key or "")),
            )
            conn.execute("COMMIT")
            return bool(cur.rowcount)
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    data = _load_policy()
    group = data.get("groups", {}).get(_group_id(group_id), {})
    policies = group.get("policies", {})
    if not isinstance(policies, dict) or key not in policies:
        return False
    policies.pop(key, None)
    _save_policy(data)
    return True


def consume_group_policy_turn(group_id: str) -> None:
    if _use_sqlite_store():
        conn = _with_sqlite()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                DELETE FROM behavior_policies
                WHERE group_id=? AND remaining_turns IS NOT NULL AND remaining_turns <= 1
                """,
                (_group_id(group_id),),
            )
            conn.execute(
                """
                UPDATE behavior_policies
                SET remaining_turns = remaining_turns - 1
                WHERE group_id=? AND remaining_turns IS NOT NULL AND remaining_turns > 1
                """,
                (_group_id(group_id),),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        return

    data = _load_policy()
    group = data.get("groups", {}).get(_group_id(group_id), {})
    policies = group.get("policies", {})
    if not isinstance(policies, dict) or not policies:
        return
    changed = False
    for key in list(policies.keys()):
        item = policies.get(key) or {}
        if "ttl_turns" not in item:
            continue
        remaining = max(0, int(item.get("ttl_turns") or 0) - 1)
        if remaining <= 0:
            policies.pop(key, None)
        else:
            item["ttl_turns"] = remaining
        changed = True
    if changed:
        _save_policy(data)


def set_render_preference(group_id: str, target: str, value: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    return set_group_policy(
        group_id,
        "render.{0}".format(str(target or "").strip()),
        dict(value or {}),
        mode="soft",
        reason=reason,
        source="ui_preferences",
    )


def get_render_preference(group_id: str, target: str) -> Dict[str, Any]:
    item = get_group_policy(group_id, "render.{0}".format(str(target or "").strip()))
    value = item.get("value")
    return dict(value) if isinstance(value, dict) else {}


def set_phrase_style(group_id: str, phrase: str, value: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    phrase = str(phrase or "").strip()
    if not phrase:
        raise ValueError("empty behavior policy phrase")
    if _use_sqlite_store():
        conn = _with_sqlite()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT value_json FROM behavior_phrase_styles
                WHERE group_id=? AND phrase=?
                """,
                (_group_id(group_id), phrase),
            ).fetchone()
            if row:
                try:
                    rule = json.loads(row[0])
                except Exception:
                    rule = {}
            else:
                rule = {}
            if not isinstance(rule, dict):
                rule = {}
            rule["phrase"] = phrase
            rule.update(dict(value or {}))
            if reason:
                rule["reason"] = str(reason)
            conn.execute(
                """
                INSERT OR REPLACE INTO behavior_phrase_styles
                (group_id, phrase, value_json)
                VALUES (?, ?, ?)
                """,
                (
                    _group_id(group_id),
                    phrase,
                    json.dumps(rule, ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.execute("COMMIT")
            return dict(rule)
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    data = _load_policy()
    group = data.setdefault("groups", {}).setdefault(_group_id(group_id), {})
    rules = group.setdefault("phrase_styles", [])
    if not isinstance(rules, list):
        rules = []
        group["phrase_styles"] = rules
    rule = next((item for item in rules if isinstance(item, dict) and item.get("phrase") == phrase), None)
    if rule is None:
        rule = {"phrase": phrase}
        rules.append(rule)
    rule.update(dict(value or {}))
    if reason:
        rule["reason"] = str(reason)
    _save_policy(data)
    return dict(rule)


def get_phrase_styles(group_id: str):
    if _use_sqlite_store():
        conn = _with_sqlite()
        try:
            rows = conn.execute(
                """
                SELECT value_json FROM behavior_phrase_styles
                WHERE group_id=?
                ORDER BY phrase
                """,
                (_group_id(group_id),),
            ).fetchall()
            result = []
            for row in rows:
                try:
                    value = json.loads(row[0])
                except Exception:
                    value = {}
                if isinstance(value, dict):
                    result.append(value)
            return result
        finally:
            conn.close()

    data = _load_policy()
    rules = data.get("groups", {}).get(_group_id(group_id), {}).get("phrase_styles", [])
    return list(rules) if isinstance(rules, list) else []


def set_tool_disabled(group_id: str, tool_name: str, turns: int = 10, reason: str = "") -> Dict[str, Any]:
    name = str(tool_name or "").strip()
    if not name:
        raise ValueError("tool_name is required")
    return set_group_policy(
        group_id,
        "tool.{0}.disabled".format(name),
        True,
        mode="soft",
        ttl_turns=turns,
        reason=reason,
        source="tool_policy",
    )


def get_disabled_tools(group_id: str) -> Set[str]:
    disabled = set()
    for key, item in list_group_policies(group_id).items():
        if not key.startswith("tool.") or not key.endswith(".disabled"):
            continue
        if item.get("value") is True:
            disabled.add(key[len("tool."):-len(".disabled")])
    return disabled


def parse_policy_value(value: str = "", value_json: str = ""):
    raw_json = str(value_json or "").strip()
    if raw_json:
        return json.loads(raw_json)
    raw = str(value or "").strip()
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    return raw


def format_policy_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def format_group_policies(group_id: str) -> str:
    policies = list_group_policies(group_id)
    if not policies:
        return "当前群没有行为策略。"
    lines = ["当前群行为策略："]
    for key in sorted(policies.keys()):
        item = policies[key]
        ttl = " ttl={0}".format(item["ttl_turns"]) if item.get("ttl_turns") else ""
        reason = " 原因：{0}".format(item.get("reason")) if item.get("reason") else ""
        lines.append("- {0}={1}{2}{3}".format(key, format_policy_value(item.get("value")), ttl, reason))
    return "\n".join(lines)


def _parse_turns(text: str, default: int = 10) -> int:
    match = re.search(r"(\d+)\s*轮", text)
    if match:
        return max(1, min(int(match.group(1)), 100))
    for word, value in CHINESE_NUMBERS.items():
        if "{0}轮".format(word) in text:
            return value
    return default


def parse_behavior_policy_instruction(text: str) -> Dict[str, Any]:
    # Keep natural-language policy detection centralized. This is intentionally
    # narrow: it catches explicit behavior-policy requests and writes them via
    # update_behavior_policy instead of scattering one-off state flags.
    value = str(text or "").strip()
    if not value:
        return {}
    compact = value.replace(" ", "").lower()

    route_scope_markers = ("实事性", "实时", "当前事实", "最新", "新闻", "转会", "伤病", "官宣")
    route_persist_markers = ("以后", "以后类似", "统一", "默认", "优先")
    if (
        any(marker in value for marker in route_scope_markers)
        and any(marker in value for marker in route_persist_markers)
        and (
            "grok" in compact
            or "grokresearch" in compact
            or "grok-research" in compact
            or "grok_search" in compact
        )
    ):
        return {
            "key": "route.public_current_fact.preferred_tool",
            "value_json": json.dumps("grok_search"),
            "reason": value,
        }

    if ("tool" in compact or "工具" in value or "调用" in value) and re.search(r"[A-Za-z_][A-Za-z0-9_]*", value):
        return {}

    emoji_markers = ("表情", "emoji", "发图", "发表情")
    disable_markers = ("不要", "别", "禁止", "禁用", "不许", "停止")
    enable_markers = ("恢复", "可以", "允许", "继续")
    if any(marker in compact for marker in emoji_markers):
        if any(marker in compact for marker in disable_markers):
            return {
                "key": "emoji.enabled",
                "value_json": "false",
                "ttl_turns": _parse_turns(value),
                "reason": value,
            }
        if any(marker in compact for marker in enable_markers):
            return {
                "key": "emoji.enabled",
                "value_json": "true",
                "reason": value,
            }
    return {}
