import os
from typing import Dict, List


class EnvService:
    def __init__(self, env_file: str, whitelist: List[str]):
        self.env_file = env_file
        self.whitelist = list(whitelist)

    def _read_lines(self) -> List[str]:
        if not os.path.exists(self.env_file):
            return []
        with open(self.env_file, "r", encoding="utf-8") as f:
            return f.read().splitlines()

    def _parse(self) -> Dict[str, str]:
        values = {}
        for line in self._read_lines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
        return values

    def _mask(self, value: str) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return value[:2] + "****"
        return value[:3] + "****" + value[-4:]

    def _should_mask(self, key: str) -> bool:
        upper_key = key.upper()
        return any(secret_part in upper_key for secret_part in ["KEY", "TOKEN", "SECRET", "PASSWORD"])

    def _display_value(self, key: str, value: str) -> str:
        if self._should_mask(key):
            return self._mask(value)
        return value

    def get(self, key: str) -> str:
        if key not in self.whitelist:
            raise ValueError("key not allowed")
        return self._parse().get(key, "")

    def check_effective(self, key: str) -> Dict[str, object]:
        if key not in self.whitelist:
            raise ValueError("key not allowed")
        file_value = self._parse().get(key, "")
        runtime_value = os.environ.get(key, "")
        return {
            "name": key,
            "exists": bool(file_value),
            "file_value": self._display_value(key, file_value),
            "runtime_value": self._display_value(key, runtime_value),
            "runtime_exists": bool(runtime_value),
            "effective": file_value == runtime_value,
            "requires_bot_restart": True,
            "note": "Dashboard API runtime is synced immediately; the QQ bot process reads this setting on restart.",
        }

    def list_masked(self) -> List[Dict[str, object]]:
        values = self._parse()
        return [
            {"name": key, "exists": bool(values.get(key)), "masked": self._display_value(key, values.get(key, ""))}
            for key in self.whitelist
        ]

    def update(self, key: str, value: str) -> None:
        if key not in self.whitelist:
            raise ValueError("key not allowed")
        lines = self._read_lines()
        new_line = key + "=" + value
        replaced = False
        output = []
        for line in lines:
            if line.strip().startswith(key + "="):
                output.append(new_line)
                replaced = True
            else:
                output.append(line)
        if not replaced:
            output.append(new_line)
        parent = os.path.dirname(self.env_file)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        with open(self.env_file, "w", encoding="utf-8") as f:
            f.write("\n".join(output) + "\n")
        os.environ[key] = value
