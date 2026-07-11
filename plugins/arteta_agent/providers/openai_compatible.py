import json
import asyncio
from dataclasses import dataclass
from typing import List, Optional

import httpx


class ProviderResponseError(Exception):
    """Raised when an LLM provider response cannot be interpreted safely."""


def _json_object_keys(raw_arguments) -> set:
    try:
        value = json.loads(raw_arguments or "{}")
    except (TypeError, ValueError):
        return set()
    if not isinstance(value, dict):
        return set()
    return set(str(key) for key in value.keys())


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_tool_history: bool = True
    supports_json_schema: bool = False
    preserves_reasoning_content: bool = True


def parse_chat_response(resp, api_url: str) -> dict:
    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        content_type = resp.headers.get("content-type", "unknown")
        snippet = (getattr(resp, "text", "") or "").strip().replace("\n", " ")
        if len(snippet) > 160:
            snippet = snippet[:157] + "..."
        if not snippet:
            snippet = "<empty>"
        raise ProviderResponseError(
            "LLM provider returned non-JSON response from {0} (HTTP {1}, content-type={2}, body={3})".format(
                api_url,
                getattr(resp, "status_code", "unknown"),
                content_type,
                snippet,
            )
        ) from exc

    try:
        return data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderResponseError(
            "LLM provider returned malformed JSON from {0} (HTTP {1})".format(
                api_url,
                getattr(resp, "status_code", "unknown"),
            )
        ) from exc


class OpenAICompatibleProvider:
    def __init__(
        self,
        client,
        api_url: str,
        capabilities: Optional[ProviderCapabilities] = None,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        retry_status_codes: Optional[set] = None,
    ) -> None:
        self.client = client
        self.api_url = api_url
        self.capabilities = capabilities or ProviderCapabilities()
        self.max_retries = max(0, int(max_retries or 0))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds or 0.0))
        self.retry_status_codes = retry_status_codes or {408, 429, 500, 502, 503, 504}

    def _should_retry_error(self, exc) -> bool:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code is not None:
            return int(status_code) in self.retry_status_codes
        return isinstance(exc, (TimeoutError, httpx.TimeoutException, httpx.TransportError))

    def _encode_messages(self, messages: List[dict]) -> List[dict]:
        if self.capabilities.supports_tool_history:
            return list(messages or [])

        encoded = []
        for message in messages or []:
            role = message.get("role")
            if role == "tool":
                encoded.append({
                    "role": "user",
                    "content": (
                        "UNTRUSTED_TOOL_RESULT:\n"
                        "tool_call_id={0}\n"
                        "{1}"
                    ).format(
                        str(message.get("tool_call_id") or ""),
                        str(message.get("content") or ""),
                    ),
                })
                continue
            if message.get("tool_calls"):
                call_summaries = []
                for tool_call in message.get("tool_calls") or []:
                    function = tool_call.get("function") or {}
                    call_summaries.append({
                        "id": tool_call.get("id", ""),
                        "name": function.get("name", ""),
                        "arg_keys": sorted(list(_json_object_keys(function.get("arguments")))),
                    })
                encoded.append({
                    "role": "assistant",
                    "content": "Requested tool calls: {0}".format(
                        json.dumps(call_summaries, ensure_ascii=False)
                    ),
                })
                continue
            encoded.append(dict(message))
        return encoded

    async def _sleep_before_retry(self, attempt_index: int) -> None:
        if self.retry_backoff_seconds <= 0:
            return
        await asyncio.sleep(self.retry_backoff_seconds * (2 ** attempt_index))

    async def chat(
        self,
        messages: List[dict],
        model: str,
        api_key: str,
        tools: Optional[List[dict]] = None,
        temperature: float = 0.9,
        timeout: float = 80.0,
        extra_payload: Optional[dict] = None,
    ) -> dict:
        payload = {
            "model": model,
            "messages": self._encode_messages(messages),
            "temperature": temperature,
        }
        if extra_payload:
            payload.update(dict(extra_payload))
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        attempts = self.max_retries + 1
        for attempt_index in range(attempts):
            try:
                resp = await self.client.post(
                    self.api_url,
                    headers={"Authorization": "Bearer {0}".format(api_key)},
                    json=payload,
                    timeout=timeout,
                )
                resp.raise_for_status()
                break
            except Exception as exc:
                if attempt_index >= self.max_retries or not self._should_retry_error(exc):
                    raise
                await self._sleep_before_retry(attempt_index)
        msg = parse_chat_response(resp, self.api_url)
        out = {"role": msg["role"], "content": msg.get("content", "")}
        if msg.get("tool_calls"):
            out["tool_calls"] = msg["tool_calls"]
        if msg.get("reasoning_content"):
            out["reasoning_content"] = msg["reasoning_content"]
        return out
