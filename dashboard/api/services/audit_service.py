import os
from datetime import datetime
from typing import Optional


class AuditService:
    def __init__(self, path: str):
        self.path = path

    def record(self, action: str, target: str, result: str, actor: Optional[str] = "admin") -> None:
        parent = os.path.dirname(self.path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        line = "{} | actor={} | action={} | target={} | result={}\n".format(
            datetime.now().isoformat(timespec="seconds"), actor, action, target, result
        )
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)
