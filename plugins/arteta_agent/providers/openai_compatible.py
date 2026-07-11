import json
from dataclasses import dataclass
from typing import List, Optional


class ProviderResponseError(Exception):
    """Raised when an LLM provider response cannot be interpreted safely."""


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
    ) -> None:
        self.client = client
        self.api_url = api_url
        self.capabilities = capabilities or ProviderCapabilities()

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
            "messages": messages,
            "temperature": temperature,
        }
        if extra_payload:
            payload.update(dict(extra_payload))
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        resp = await self.client.post(
            self.api_url,
            headers={"Authorization": "Bearer {0}".format(api_key)},
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        msg = parse_chat_response(resp, self.api_url)
        out = {"role": msg["role"], "content": msg.get("content", "")}
        if msg.get("tool_calls"):
            out["tool_calls"] = msg["tool_calls"]
        if msg.get("reasoning_content"):
            out["reasoning_content"] = msg["reasoning_content"]
        return out
