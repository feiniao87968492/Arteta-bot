"""Grouped provider configuration, verification, and recoverable apply flow."""

import asyncio
import base64
import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import httpx

from dashboard.api.services.env_service import EnvService
from plugins.arteta_vision import _build_vision_api_request, _extract_vision_api_response


VERIFY_TIMEOUT = 20.0
RECEIPT_TTL_SECONDS = 300.0
_ONE_PIXEL_PNG = "data:image/png;base64," + base64.b64encode(
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05"
    b"\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
).decode("ascii")
_X_FETCH_PROBE_URL = "https://x.com/Arsenal/status/1"


class ProviderConfigError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProviderField:
    name: str
    label: str
    secret: bool = False


@dataclass(frozen=True)
class ProviderDefinition:
    identifier: str
    label: str
    fields: Tuple[ProviderField, ...]


PROVIDERS = (
    ProviderDefinition(
        "chat",
        "对话",
        (
            ProviderField("DEEPSEEK_API_URL", "API URL"),
            ProviderField("DEEPSEEK_MODEL", "模型"),
            ProviderField("DEEPSEEK_API_KEY", "API Key", True),
            ProviderField("DEEPSEEK_TEMPERATURE", "温度"),
        ),
    ),
    ProviderDefinition(
        "algorithm",
        "算法解题",
        (
            ProviderField("ALGO_API_URL", "API URL"),
            ProviderField("ALGO_MODEL", "模型"),
            ProviderField("ALGO_API_KEY", "API Key", True),
        ),
    ),
    ProviderDefinition(
        "image_generation",
        "图片生成",
        (
            ProviderField("IMAGE_API_URL", "API URL"),
            ProviderField("IMAGE_MODEL", "模型"),
            ProviderField("IMAGE_API_KEY", "API Key", True),
        ),
    ),
    ProviderDefinition(
        "vision",
        "图片识别",
        (
            ProviderField("VISION_API_URL", "API URL"),
            ProviderField("VISION_MODEL", "模型"),
            ProviderField("VISION_API_KEY", "API Key", True),
            ProviderField("VISION_TIMEOUT", "超时（秒）"),
        ),
    ),
    ProviderDefinition(
        "football_data",
        "足球数据",
        (ProviderField("FOOTBALL_API_TOKEN", "API Token", True),),
    ),
    ProviderDefinition(
        "grok_search",
        "Grok 搜索",
        (
            ProviderField("ARTETA_GROKSEARCH_API_URL", "API URL"),
            ProviderField("ARTETA_GROKSEARCH_MODEL", "模型"),
            ProviderField("ARTETA_GROKSEARCH_API_KEY", "API Key", True),
            ProviderField("ARTETA_GROKSEARCH_TIMEOUT", "超时（秒）"),
        ),
    ),
    ProviderDefinition(
        "x_fetch",
        "X Fetch",
        (
            ProviderField("ARTETA_X_FETCH_API_URL", "API URL"),
            ProviderField("ARTETA_X_FETCH_API_KEY", "API Key", True),
        ),
    ),
)
_PROVIDERS_BY_ID = {definition.identifier: definition for definition in PROVIDERS}


def provider_field_names() -> Tuple[str, ...]:
    return tuple(field.name for provider in PROVIDERS for field in provider.fields)


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return value[:2] + "****"
    return value[:3] + "****" + value[-4:]


def _join_base_url(base_url: str, path: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if base.endswith("/v1") and path.startswith("/v1/"):
        path = path[3:]
    return base + path


class ProviderConfigService:
    def __init__(self, env_service: EnvService, now: Optional[Callable[[], float]] = None):
        self.env_service = env_service
        self._now = now or time.monotonic
        self._receipts = {}  # type: Dict[str, Dict[str, object]]
        self._apply_lock = threading.RLock()

    def list_providers(self) -> List[Dict[str, object]]:
        stored = self.env_service._parse()
        result = []
        for provider in PROVIDERS:
            fields = []
            values = {}
            for field in provider.fields:
                value = stored.get(field.name, "")
                display = _mask(value) if field.secret else value
                fields.append({
                    "name": field.name,
                    "label": field.label,
                    "secret": field.secret,
                    "configured": bool(value),
                    "value": display,
                })
                values[field.name] = display
            result.append({
                "id": provider.identifier,
                "label": provider.label,
                "configured": all(item["configured"] for item in fields),
                "fields": fields,
                "values": values,
            })
        return result

    def _definition(self, provider_id: str) -> ProviderDefinition:
        definition = _PROVIDERS_BY_ID.get(str(provider_id or ""))
        if definition is None:
            raise ProviderConfigError("unknown_provider", "未知配置服务")
        return definition

    def _normalize_candidate(self, provider_id: str, candidate: Dict[str, object]) -> Dict[str, str]:
        definition = self._definition(provider_id)
        if not isinstance(candidate, dict):
            raise ProviderConfigError("invalid_candidate", "配置内容无效")
        expected = {field.name for field in definition.fields}
        supplied = {str(name) for name in candidate.keys()}
        if supplied != expected:
            raise ProviderConfigError("invalid_candidate", "请完整填写当前服务组的配置")
        values = {field.name: str(candidate.get(field.name, "")).strip() for field in definition.fields}
        if any(not value for value in values.values()):
            raise ProviderConfigError("invalid_candidate", "请完整填写当前服务组的配置")
        if any("\n" in value or "\r" in value or "\x00" in value for value in values.values()):
            raise ProviderConfigError("invalid_candidate", "配置字段不能包含控制字符")
        self._validate_local_values(provider_id, values)
        return values

    def _validate_local_values(self, provider_id: str, values: Dict[str, str]) -> None:
        for name, value in values.items():
            if name.endswith("_URL") and not value.lower().startswith(("https://", "http://")):
                raise ProviderConfigError("invalid_candidate", "API URL 必须以 http:// 或 https:// 开头")
        if provider_id in ("chat", "algorithm") and not values[next(name for name in values if name.endswith("_URL"))].rstrip("/").endswith("/chat/completions"):
            raise ProviderConfigError("invalid_candidate", "对话服务 URL 必须是完整的 /chat/completions 地址")
        if "DEEPSEEK_TEMPERATURE" in values:
            self._bounded_float(values["DEEPSEEK_TEMPERATURE"], "温度", 0.0, 2.0)
        if "VISION_TIMEOUT" in values:
            self._bounded_float(values["VISION_TIMEOUT"], "超时", 1.0, 180.0)
        if "ARTETA_GROKSEARCH_TIMEOUT" in values:
            self._bounded_float(values["ARTETA_GROKSEARCH_TIMEOUT"], "超时", 1.0, 180.0)

    def _bounded_float(self, value: str, label: str, minimum: float, maximum: float) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            raise ProviderConfigError("invalid_candidate", label + "必须是数字")
        if result < minimum or result > maximum:
            raise ProviderConfigError("invalid_candidate", label + "不在允许范围内")
        return result

    def _digest(self, provider_id: str, values: Dict[str, str]) -> str:
        payload = json.dumps({"provider": provider_id, "values": values}, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def verify(self, provider_id: str, candidate: Dict[str, object], actor: str = "admin") -> Dict[str, object]:
        values = self._normalize_candidate(provider_id, candidate)
        try:
            await self._verify_remote(provider_id, values)
        except ProviderConfigError:
            raise
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError, IndexError, TypeError):
            raise ProviderConfigError("verification_failed", "服务验证失败，请检查 URL、模型和凭据")
        receipt = secrets.token_urlsafe(24)
        self._receipts[receipt] = {
            "provider": provider_id,
            "digest": self._digest(provider_id, values),
            "actor": str(actor or "admin"),
            "expires_at": self._now() + RECEIPT_TTL_SECONDS,
        }
        return {"provider": provider_id, "receipt": receipt, "expires_in": int(RECEIPT_TTL_SECONDS)}

    async def _verify_remote(self, provider_id: str, values: Dict[str, str]) -> None:
        if provider_id in ("chat", "algorithm"):
            await self._verify_chat(values)
        elif provider_id == "image_generation":
            await self._verify_image_generation(values)
        elif provider_id == "vision":
            await self._verify_vision(values)
        elif provider_id == "football_data":
            await self._verify_football_data(values)
        elif provider_id == "grok_search":
            await self._verify_grok_search(values)
        elif provider_id == "x_fetch":
            await self._verify_x_fetch(values)
        else:
            raise ProviderConfigError("unknown_provider", "未知配置服务")

    async def _verify_chat(self, values: Dict[str, str]) -> None:
        prefix = "DEEPSEEK" if "DEEPSEEK_API_URL" in values else "ALGO"
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT) as client:
            response = await client.post(
                values[prefix + "_API_URL"],
                headers={"Authorization": "Bearer " + values[prefix + "_API_KEY"]},
                json={
                    "model": values[prefix + "_MODEL"],
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                    "temperature": 0,
                },
            )
        self._require_success(response)
        body = response.json()
        choices = body.get("choices") if isinstance(body, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ProviderConfigError("verification_failed", "服务验证失败，请检查 URL、模型和凭据")

    async def _verify_image_generation(self, values: Dict[str, str]) -> None:
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT) as client:
            response = await client.get(
                _join_base_url(values["IMAGE_API_URL"], "/v1/models"),
                headers={"Authorization": "Bearer " + values["IMAGE_API_KEY"]},
            )
        self._require_success(response)
        body = response.json()
        models = body.get("data") if isinstance(body, dict) else None
        if isinstance(models, list) and models:
            model_ids = {str(item.get("id", "")) for item in models if isinstance(item, dict)}
            if model_ids and values["IMAGE_MODEL"] not in model_ids:
                raise ProviderConfigError("model_unavailable", "填写的图片模型不可用")
        elif not isinstance(body, dict):
            raise ProviderConfigError("verification_failed", "服务返回格式无效")

    async def _verify_vision(self, values: Dict[str, str]) -> None:
        timeout = self._bounded_float(values["VISION_TIMEOUT"], "超时", 1.0, 180.0)
        url, headers, payload = _build_vision_api_request(
            values["VISION_API_URL"],
            values["VISION_API_KEY"],
            values["VISION_MODEL"],
            _ONE_PIXEL_PNG,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
        self._require_success(response)
        text = _extract_vision_api_response(values["VISION_API_URL"], response.json())
        if not text:
            raise ProviderConfigError("verification_failed", "服务返回格式无效")

    async def _verify_football_data(self, values: Dict[str, str]) -> None:
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT) as client:
            response = await client.get(
                "https://api.football-data.org/v4/competitions/PL/standings",
                headers={"X-Auth-Token": values["FOOTBALL_API_TOKEN"]},
            )
        self._require_success(response)
        body = response.json()
        if not isinstance(body, dict) or "standings" not in body:
            raise ProviderConfigError("verification_failed", "服务返回格式无效")

    async def _verify_grok_search(self, values: Dict[str, str]) -> None:
        timeout = self._bounded_float(values["ARTETA_GROKSEARCH_TIMEOUT"], "超时", 1.0, 180.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                _join_base_url(values["ARTETA_GROKSEARCH_API_URL"], "/web_search"),
                headers={"Authorization": "Bearer " + values["ARTETA_GROKSEARCH_API_KEY"]},
                json={"query": "Arsenal", "max_results": 1, "freshness": "recent", "model": values["ARTETA_GROKSEARCH_MODEL"]},
            )
        self._require_success(response)
        if not isinstance(response.json(), dict):
            raise ProviderConfigError("verification_failed", "服务返回格式无效")

    async def _verify_x_fetch(self, values: Dict[str, str]) -> None:
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT) as client:
            response = await client.post(
                _join_base_url(values["ARTETA_X_FETCH_API_URL"], "/fetch"),
                headers={"Authorization": "Bearer " + values["ARTETA_X_FETCH_API_KEY"]},
                json={"url": _X_FETCH_PROBE_URL},
            )
        self._require_success(response)
        if not isinstance(response.json(), dict):
            raise ProviderConfigError("verification_failed", "服务返回格式无效")

    def _require_success(self, response: httpx.Response) -> None:
        if response.status_code != 200:
            raise ProviderConfigError("verification_failed", "服务验证失败，请检查 URL、模型和凭据")

    def _consume_receipt(self, provider_id: str, values: Dict[str, str], receipt: str, actor: str) -> None:
        item = self._receipts.get(str(receipt or ""))
        if not item:
            raise ProviderConfigError("invalid_receipt", "验证凭据无效或已使用")
        valid = (
            item.get("provider") == provider_id
            and item.get("digest") == self._digest(provider_id, values)
            and item.get("actor") == str(actor or "admin")
            and float(item.get("expires_at", 0.0)) >= self._now()
        )
        if not valid:
            raise ProviderConfigError("invalid_receipt", "验证凭据无效、已过期或不匹配当前配置")
        del self._receipts[str(receipt)]

    def apply(
        self,
        provider_id: str,
        candidate: Dict[str, object],
        receipt: str,
        actor: str = "admin",
        restart: Optional[Callable[[], object]] = None,
    ) -> Dict[str, object]:
        values = self._normalize_candidate(provider_id, candidate)
        with self._apply_lock:
            return self._apply_verified(provider_id, values, receipt, actor, restart)

    def _apply_verified(
        self,
        provider_id: str,
        values: Dict[str, str],
        receipt: str,
        actor: str,
        restart: Optional[Callable[[], object]],
    ) -> Dict[str, object]:
        self._consume_receipt(provider_id, values, receipt, actor)
        if restart is None:
            raise ProviderConfigError("restart_unavailable", "机器人重启不可用")
        original = self.env_service.read_text()
        try:
            self.env_service.replace_values_atomic(values)
        except OSError:
            try:
                self.env_service.write_text_atomic(original)
            except OSError:
                pass
            raise ProviderConfigError("persistence_failed", "配置保存失败，原配置未应用")

        result = restart()
        returncode = int(getattr(result, "returncode", 1))
        if returncode == 0:
            return {
                "provider": provider_id,
                "active": True,
                "persistence_succeeded": True,
                "initial_restart_failed": False,
                "rolled_back": False,
                "recovery_active": False,
                "recovery_restart_succeeded": False,
                "restart_error": "",
            }

        restart_error = "bot restart failed"
        rolled_back = False
        recovery_active = False
        try:
            self.env_service.write_text_atomic(original)
            rolled_back = True
            recovery = restart()
            recovery_active = int(getattr(recovery, "returncode", 1)) == 0
        except OSError:
            rolled_back = False
        return {
            "provider": provider_id,
            "active": False,
            "persistence_succeeded": True,
            "initial_restart_failed": True,
            "rolled_back": rolled_back,
            "recovery_active": recovery_active,
            "recovery_restart_succeeded": recovery_active,
            "restart_error": restart_error,
        }
