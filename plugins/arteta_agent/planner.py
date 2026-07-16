from .context import ToolContext
from .providers.chat_completion import (
    DEFAULT_CHAT_API_URL,
    call_llm_with_tools as provider_call_llm_with_tools,
)
from .providers.openai_compatible import (
    ProviderResponseError,
    parse_chat_response,
)
from .runtime.confirmation import (
    latest_user_content,
)
from .service import AgentRequest, run_agent_request


def _parse_chat_response(resp, api_url: str):
    return parse_chat_response(resp, api_url)


def _latest_user_content(messages) -> str:
    return latest_user_content(messages)


async def call_llm_with_tools(messages, model: str, api_key: str, api_url: str = DEFAULT_CHAT_API_URL, allowed_permissions=None, disabled_tools=None, temperature: float = 0.9, request_timeout: float = 80.0):
    return await provider_call_llm_with_tools(
        messages=messages,
        model=model,
        api_key=api_key,
        api_url=api_url,
        allowed_permissions=allowed_permissions,
        disabled_tools=disabled_tools,
        temperature=temperature,
        request_timeout=request_timeout,
    )


async def run_agent_loop(messages, ctx: ToolContext, model: str, api_key: str, api_url: str = DEFAULT_CHAT_API_URL, max_rounds: int = 6, trace=None, temperature: float = 0.9, request_timeout: float = 80.0, model_call_timeout: float = None, max_tool_calls: int = 10, max_same_tool_call_repeats: int = 2, max_total_observation_chars: int = 80000, progress_observer=None):
    # Agent loop entrypoint used by arteta_chat.py when
    # ARTETA_USE_AGENT_REGISTRY=true. It alternates LLM planning and
    # permission-checked tool execution until the model returns final text.
    return await run_agent_request(AgentRequest(
        messages=list(messages),
        ctx=ctx,
        model=model,
        api_key=api_key,
        api_url=api_url,
        max_rounds=max_rounds,
        trace=trace,
        temperature=temperature,
        request_timeout=request_timeout,
        model_call_timeout=model_call_timeout if model_call_timeout is not None else request_timeout,
        max_tool_calls=max_tool_calls,
        max_same_tool_call_repeats=max_same_tool_call_repeats,
        max_total_observation_chars=max_total_observation_chars,
        chat_model_call=call_llm_with_tools,
        progress_observer=progress_observer,
    ))
