import os
import time

from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool


ARTIFACT_DIR = os.path.join("artifacts", "agent_tools")


def _get_arteta_render():
    from plugins import arteta_render

    return arteta_render


def _write_artifact(prefix: str, content: bytes) -> str:
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    filename = "{0}_{1}.png".format(prefix, int(time.time() * 1000))
    path = os.path.join(ARTIFACT_DIR, filename)
    with open(path, "wb") as fh:
        fh.write(content)
    return path


async def render_markdown_to_image(ctx: ToolContext, markdown: str) -> str:
    text = str(markdown or "").strip()
    if not text:
        return "请提供要渲染的 Markdown 文本。"
    renderer = _get_arteta_render()
    style_tags_to_html = getattr(renderer, "style_tags_to_html", lambda value: value)
    image_bytes = await renderer.html_to_image(style_tags_to_html(text))
    path = _write_artifact("render_markdown", image_bytes)
    return "[RenderedImage: {0}]".format(path)


def render_text_to_tactical_board(ctx: ToolContext, text: str) -> str:
    body = str(text or "").strip()
    if not body:
        return "请提供要渲染的文本。"
    image_bytes = _get_arteta_render().text_to_tactical_board(body)
    path = _write_artifact("tactical_board", image_bytes)
    return "[RenderedImage: {0}]".format(path)


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="render_markdown_to_image",
        description="把 Markdown/公式/代码文本渲染为本地 PNG artifact，返回 [RenderedImage: path]，不直接发送 QQ 消息。",
        parameters={
            "type": "object",
            "properties": {"markdown": {"type": "string", "description": "要渲染的 Markdown 文本"}},
            "required": ["markdown"],
        },
        handler=render_markdown_to_image,
        permission="safe_write",
        category="render",
        timeout_seconds=40.0,
    ))
    ensure_tool(ToolSpec(
        name="render_text_to_tactical_board",
        description="把普通文本渲染为战术板风格本地 PNG artifact，返回 [RenderedImage: path]。",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "要渲染的文本"}},
            "required": ["text"],
        },
        handler=render_text_to_tactical_board,
        permission="safe_write",
        category="render",
        timeout_seconds=20.0,
    ))
