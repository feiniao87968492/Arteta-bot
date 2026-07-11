import base64
import os
import time

import httpx

from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool


ARTIFACT_DIR = os.path.join("artifacts", "agent_tools")


def _get_arteta_image():
    from plugins import arteta_image

    return arteta_image


def _get_arteta_chat():
    from plugins import arteta_chat

    return arteta_chat


async def _request_generated_image(prompt: str, size: str = "1024x1024") -> bytes:
    arteta_image = _get_arteta_image()
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            "{0}/v1/images/generations".format(arteta_image.IMAGE_API_URL),
            headers={"Authorization": "Bearer {0}".format(arteta_image.IMAGE_API_KEY)},
            json={
                "model": arteta_image.IMAGE_MODEL,
                "prompt": prompt,
                "n": 1,
                "size": size,
            },
        )
        resp.raise_for_status()
        item = resp.json()["data"][0]
        if "b64_json" in item:
            return base64.b64decode(item["b64_json"])
        if "url" in item:
            image_resp = await client.get(item["url"])
            image_resp.raise_for_status()
            return image_resp.content
        raise RuntimeError("image API response did not include b64_json or url")


def _write_image(content: bytes) -> str:
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    path = os.path.join(ARTIFACT_DIR, "generated_image_{0}.png".format(int(time.time() * 1000)))
    with open(path, "wb") as fh:
        fh.write(content)
    return path


async def generate_image(ctx: ToolContext, prompt: str, size: str = "1024x1024") -> str:
    # Generation is safe_write because it creates a local artifact only; it
    # does not send the image to QQ directly.
    text = str(prompt or "").strip()
    if not text:
        return "请提供图片生成提示词。"
    content = await _request_generated_image(text, size=size or "1024x1024")
    path = _write_image(content)
    return "[GeneratedImage: {0}]".format(path)


async def analyze_image(ctx: ToolContext, image_index: int = 0) -> str:
    # Image understanding is a registry tool so it appears in Agent Trace
    # instead of being hidden in chat pre-processing.
    urls = list((ctx.extra or {}).get("image_urls") or [])
    if not urls:
        if ctx.image_analysis:
            return ctx.image_analysis
        return "当前消息没有可识别的图片。"
    try:
        index = int(image_index or 0)
    except (TypeError, ValueError):
        index = 0
    if index < 0 or index >= len(urls):
        return "图片序号超出范围，当前共有 {0} 张图片。".format(len(urls))
    desc = await _get_arteta_chat().analyze_image(str(urls[index]))
    return "图片 {0}/{1}：{2}".format(index + 1, len(urls), desc)


def register_tools() -> None:
    # analyze_image is registered separately from generate_image so image
    # recognition remains safe_read and visible in Agent Trace.
    ensure_tool(ToolSpec(
        name="analyze_image",
        description="识别当前消息中的图片内容。默认分析第 1 张图片，返回文字描述，不直接发送 QQ 消息。",
        parameters={
            "type": "object",
            "properties": {
                "image_index": {"type": "integer", "description": "从 0 开始的图片序号", "default": 0},
            },
            "required": [],
        },
        handler=analyze_image,
        permission="safe_read",
        category="image",
        timeout_seconds=80.0,
    ))
    ensure_tool(ToolSpec(
        name="generate_image",
        description="根据提示词生成图片并保存为本地 PNG artifact，返回 [GeneratedImage: path]，不直接发送 QQ 消息。",
        parameters={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "图片生成提示词"},
                "size": {"type": "string", "description": "图片尺寸", "default": "1024x1024"},
            },
            "required": ["prompt"],
        },
        handler=generate_image,
        permission="safe_write",
        category="image",
        timeout_seconds=190.0,
    ))
