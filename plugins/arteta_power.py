# plugins/arteta_power.py
"""
机器人全局电源开关（Bot 进程与 Dashboard 进程共享）。

数据文件: ARTETA_POWER_FILE 或默认 <repo>/data/bot_power.json
{
  "enabled": true,
  "updated_at": "2026-05-28T10:00:00",
  "actor": "dashboard",
  "reason": ""
}

读取使用 mtime 缓存，避免每条消息都打开磁盘。
关闭后：A/塔子/at 等对话指令、/算法 指令、daily/weekly 定时任务一律跳过；
        工具型指令（赞我、画图、查档等）保持可用。
"""

import json
import os
import threading
from datetime import datetime
from typing import Dict, Optional

from loguru import logger

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_DEFAULT_PATH = os.path.join(_REPO_ROOT, "data", "bot_power.json")

_lock = threading.Lock()
_cache: Optional[Dict] = None
_cache_mtime: float = 0.0


def power_file_path() -> str:
    return os.environ.get("ARTETA_POWER_FILE", _DEFAULT_PATH)


def _default_state() -> Dict:
    return {
        "enabled": True,
        "updated_at": "",
        "actor": "",
        "reason": "",
    }


def _load_locked() -> Dict:
    global _cache, _cache_mtime
    path = power_file_path()
    if not os.path.exists(path):
        _cache = _default_state()
        _cache_mtime = 0.0
        return _cache
    try:
        mtime = os.path.getmtime(path)
        if _cache is not None and mtime == _cache_mtime:
            return _cache
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        state = _default_state()
        state.update({k: data.get(k, state[k]) for k in state.keys()})
        state["enabled"] = bool(state["enabled"])
        _cache = state
        _cache_mtime = mtime
        return _cache
    except (OSError, ValueError) as exc:
        logger.warning(f"[Power] 读取 {path} 失败，按开启处理: {exc}")
        _cache = _default_state()
        _cache_mtime = 0.0
        return _cache


def get_state() -> Dict:
    """返回当前电源状态副本（不抛异常）。"""
    with _lock:
        return dict(_load_locked())


def is_bot_enabled() -> bool:
    """对话/定时任务入口调用：返回 True 时正常工作。"""
    return get_state().get("enabled", True)


def set_state(enabled: bool, actor: str = "", reason: str = "") -> Dict:
    """更新电源状态，写回磁盘并刷新缓存。"""
    global _cache, _cache_mtime
    path = power_file_path()
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    new_state = {
        "enabled": bool(enabled),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "actor": actor or "",
        "reason": reason or "",
    }
    with _lock:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(new_state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        _cache = dict(new_state)
        try:
            _cache_mtime = os.path.getmtime(path)
        except OSError:
            _cache_mtime = 0.0
    logger.info(
        f"[Power] 状态变更 enabled={new_state['enabled']} actor={new_state['actor']} reason={new_state['reason']!r}"
    )
    return dict(new_state)
