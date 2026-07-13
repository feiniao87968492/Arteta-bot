import json
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional

from .providers.http_client import get_shared_async_client
from .providers.openai_compatible import OpenAICompatibleProvider


ActivationLLMCall = Callable[[List[dict], str, str, float], Awaitable[str]]
DEFAULT_CHAT_API_URL = "https://www.boxying.com/v1/chat/completions"


@dataclass
class ActivationDecision:
    should_reply: bool
    reason: str = ""


TASK_MARKERS = (
    "查",
    "搜",
    "总结",
    "生成",
    "写",
    "解释",
    "分析",
    "帮",
    "怎么",
    "为什么",
    "最近",
    "最新",
    "目前",
    "今天",
    "本周",
    "图片",
    "照片",
    "截图",
    "识别",
    "链接",
    "网址",
    "网页",
    "http://",
    "https://",
    "文档",
    "文件",
    "pdf",
    "docx",
    "trace",
    "调用",
    "工具",
    "算法",
    "代码",
    "数学",
    "物理",
    "积分榜",
    "赛程",
    "下一场",
    "首发",
    "阵容",
    "伤病",
    "转会",
    "感兴趣",
    "有意",
    "关注",
    "队伍",
    "球队",
    "俱乐部",
    "罗马诺",
    "状态",
    "新闻",
    "周报",
    "群里",
)


def is_activation_candidate(raw_text: str, has_image: bool = False) -> bool:
    # This is only a cheap gate before the activation judge. It keeps ordinary
    # group chatter away from the LLM while allowing task-like messages through.
    text = str(raw_text or "").strip()
    if not text:
        return False
    if len(text) <= 2 and not has_image:
        return False
    if has_image and any(marker in text for marker in ("图", "图片", "照片", "截图", "识别", "看看", "讲了什么", "?", "？")):
        return True
    return any(marker in text for marker in TASK_MARKERS)


def build_activation_messages(raw_text: str, has_image: bool, group_id: str) -> List[dict]:
    return [
        {
            "role": "system",
            "content": (
                "你是 Arteta Bot 的消息触发判断 agent，只输出 JSON。"
                "格式必须是 {\"should_reply\": true|false, \"reason\": \"short reason\"}。"
                "只有当用户在请求机器人执行任务、回答问题、查询足球/阿森纳/群聊记忆、分析图片、分析链接、读取文档、查看 trace、"
                "解数学/算法/代码题，或明显需要 Arteta Bot 介入时才返回 true。"
                "普通群聊、赛事闲聊、表情包、没人点名机器人的陈述句、纯图片且无请求文本，返回 false。"
                "不要执行任务，不要生成正式回复，只判断是否应该进入主 agent。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "group_id": str(group_id or ""),
                    "has_image": bool(has_image),
                    "message": str(raw_text or "").strip(),
                },
                ensure_ascii=False,
            ),
        },
    ]


async def call_activation_llm(messages: List[dict], model: str, api_key: str, timeout: float, api_url: str = DEFAULT_CHAT_API_URL) -> str:
    provider = OpenAICompatibleProvider(
        client=get_shared_async_client(),
        api_url=api_url or DEFAULT_CHAT_API_URL,
    )
    message = await provider.chat(
        messages=messages,
        model=model,
        api_key=api_key,
        temperature=0,
        timeout=timeout,
        extra_payload={
            "max_tokens": 80,
            "response_format": {"type": "json_object"},
        },
    )
    return str(message.get("content") or "")


def _parse_decision(content: str) -> ActivationDecision:
    text = str(content or "").strip()
    if not text:
        return ActivationDecision(False, "empty activation response")
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        text = match.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ActivationDecision(False, "invalid activation response")
    return ActivationDecision(
        should_reply=bool(data.get("should_reply") is True),
        reason=str(data.get("reason") or "")[:120],
    )


async def decide_activation_with_agent(
    raw_text: str,
    has_image: bool,
    group_id: str,
    model: str,
    api_key: str,
    api_url: str = DEFAULT_CHAT_API_URL,
    timeout: float = 4.0,
    llm_call: Optional[ActivationLLMCall] = None,
) -> ActivationDecision:
    if not api_key:
        return ActivationDecision(False, "activation api key missing")
    messages = build_activation_messages(raw_text, has_image, group_id)
    try:
        if llm_call is None:
            content = await call_activation_llm(messages, model, api_key, timeout, api_url=api_url)
        else:
            content = await llm_call(messages, model, api_key, timeout)
    except Exception as exc:
        return ActivationDecision(False, "activation error: {0}".format(exc.__class__.__name__))
    return _parse_decision(content)
