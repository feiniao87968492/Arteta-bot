from .http_client import get_shared_async_client
from .openai_compatible import OpenAICompatibleProvider
from ..registry import build_openai_tools


DEFAULT_CHAT_API_URL = "https://www.boxying.com/v1/chat/completions"


async def call_llm_with_tools(
    messages,
    model: str,
    api_key: str,
    api_url: str = DEFAULT_CHAT_API_URL,
    allowed_permissions=None,
    disabled_tools=None,
    temperature: float = 0.9,
    request_timeout: float = 80.0,
):
    tools = build_openai_tools(
        include_permissions=allowed_permissions,
        exclude_names=set(disabled_tools or []),
    )
    provider = OpenAICompatibleProvider(
        client=get_shared_async_client(),
        api_url=api_url or DEFAULT_CHAT_API_URL,
    )
    return await provider.chat(
        messages=messages,
        model=model,
        api_key=api_key,
        tools=tools,
        temperature=temperature,
        timeout=float(request_timeout or 80.0),
    )
