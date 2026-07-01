import os
from typing import Dict, List


class LogsService:
    def __init__(self, logs_dir: str):
        self.logs_dir = os.path.abspath(logs_dir)

    def _resolve(self, name: str) -> str:
        target = os.path.abspath(os.path.join(self.logs_dir, name))
        if target != self.logs_dir and not target.startswith(self.logs_dir + os.sep):
            raise ValueError("path not allowed")
        return target

    def list_logs(self) -> List[Dict[str, object]]:
        if not os.path.isdir(self.logs_dir):
            return []
        logs = []
        for name in sorted(os.listdir(self.logs_dir)):
            if not name.startswith("arteta_bot") and not name.startswith("dashboard_audit"):
                continue
            full = os.path.join(self.logs_dir, name)
            if os.path.isfile(full):
                logs.append({"name": name, "size": os.path.getsize(full), "mtime": os.path.getmtime(full)})
        return logs

    def tail(self, name: str, limit: int = 200) -> List[str]:
        target = self._resolve(name)
        if not os.path.isfile(target):
            return []
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        return lines[-limit:]
