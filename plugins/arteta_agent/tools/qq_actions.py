import os
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageSequence

try:
    from nonebot.adapters.onebot.v11 import MessageSegment
except Exception:  # pragma: no cover - unit tests can run without NoneBot.
    MessageSegment = None

from ..context import ToolContext
from ..emoji.catalog import load_emoji_catalog
from ..emoji.models import EmojiAsset, EmojiReactionDecision
from ..emoji.selector import select_emoji_asset
from ..registry import ToolSpec, ensure_tool


REPO_ROOT = Path(__file__).resolve().parents[3]
EMOJI_DIR = os.environ.get("ARTETA_EMOJI_DIR", str(REPO_ROOT / "表情包"))
EMOJI_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_EMOJI_BYTES = 8 * 1024 * 1024
MAX_EMOJI_DISPLAY_EDGE = 180


async def send_like(ctx: ToolContext, user_id: str = "", times: int = 1) -> str:
    if ctx.bot is None:
        return "当前没有可用 bot，无法点赞。"
    target_id = str(user_id or ctx.user_id)
    safe_times = max(1, min(int(times or 1), 10))
    if hasattr(ctx.bot, "send_like"):
        for _ in range(safe_times):
            await ctx.bot.send_like(user_id=int(target_id))
    else:
        await ctx.bot.call_api("send_like", user_id=int(target_id), times=safe_times)
    return "已为 {0} 点赞 {1} 次。".format(target_id, safe_times)

async def send_group_message(ctx: ToolContext, message: str, group_id: str = "") -> str:
    if ctx.bot is None:
        return "No bot is available, cannot send group message."
    target_group = str(group_id or ctx.group_id)
    await ctx.bot.call_api("send_group_msg", group_id=int(target_group), message=str(message))
    return "Sent group message to {0}.".format(target_group)


def _asset_to_dict(asset: EmojiAsset) -> Dict[str, object]:
    return {
        "name": asset.name,
        "reactions": list(asset.reactions),
        "intensities": list(asset.intensities),
        "stances": list(asset.stances),
        "topics": list(asset.topics),
        "avoid_contexts": list(asset.avoid_contexts),
        "weight": asset.weight,
        "reviewed": asset.reviewed,
        "category": asset.reactions[0] if asset.reactions else "approval",
        "relative_path": asset.relative_path,
        "path": asset.path,
    }


def list_emoji_assets(base_dir: str = "") -> List[Dict[str, object]]:
    # The emoji tool is intentionally limited to this local whitelist
    # directory. The model never receives or controls arbitrary filesystem paths.
    return [_asset_to_dict(asset) for asset in load_emoji_catalog(base_dir or EMOJI_DIR)]


def choose_emoji_asset(
    mood: str = "",
    emoji_name: str = "",
    base_dir: str = "",
    reaction: str = "",
    intensity: str = "medium",
    stance: str = "shared_with_user",
    topic: str = "general",
    reason_code: str = "",
    request_id: str = "",
    group_id: str = "",
) -> Optional[Dict[str, object]]:
    assets = load_emoji_catalog(base_dir or EMOJI_DIR)
    if not assets:
        return None

    decision = EmojiReactionDecision(
        reaction=reaction or "none",
        intensity=intensity,
        stance=stance,
        topic=topic,
        confidence=0.8,
        reason_codes=[reason_code] if reason_code else [],
    )
    selected = select_emoji_asset(
        assets,
        decision,
        group_id=group_id,
        request_id=request_id,
        explicit_emoji_name=emoji_name,
        legacy_mood=mood,
    )
    if selected is None:
        return None
    return _asset_to_dict(selected)


def _build_image_segment(image_bytes: bytes):
    if MessageSegment is not None and hasattr(MessageSegment, "image"):
        return MessageSegment.image(image_bytes)
    return image_bytes


def _resize_image_to_one_third(image_bytes: bytes) -> bytes:
    with Image.open(BytesIO(image_bytes)) as image:
        target_width = max(1, image.width // 3)
        target_height = max(1, image.height // 3)
        largest_edge = max(target_width, target_height)
        if largest_edge > MAX_EMOJI_DISPLAY_EDGE:
            ratio = MAX_EMOJI_DISPLAY_EDGE / float(largest_edge)
            target_width = max(1, int(target_width * ratio))
            target_height = max(1, int(target_height * ratio))
        target_size = (target_width, target_height)
        output = BytesIO()
        fmt = (image.format or "PNG").upper()

        if fmt == "GIF" and getattr(image, "is_animated", False):
            frames = []
            durations = []
            for frame in ImageSequence.Iterator(image):
                resized = frame.convert("RGBA").resize(target_size, Image.Resampling.LANCZOS)
                frames.append(resized)
                durations.append(frame.info.get("duration", image.info.get("duration", 80)))
            frames[0].save(
                output,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                loop=image.info.get("loop", 0),
                duration=durations,
                disposal=2,
            )
            return output.getvalue()

        if fmt not in {"PNG", "JPEG", "WEBP", "GIF"}:
            fmt = "PNG"
        resized = image.convert("RGBA").resize(target_size, Image.Resampling.LANCZOS)
        save_kwargs = {}
        if fmt == "JPEG":
            resized = resized.convert("RGB")
            save_kwargs["quality"] = 90
        resized.save(output, format=fmt, **save_kwargs)
        return output.getvalue()


async def send_pending_mood_emojis(ctx: ToolContext) -> int:
    pending = list((ctx.extra or {}).get("pending_mood_emojis") or [])
    if not pending or ctx.bot is None:
        return 0

    sent = 0
    remaining = []
    for item in pending:
        try:
            path = Path(item["path"])
            image_bytes = _resize_image_to_one_third(path.read_bytes())
            image_message = _build_image_segment(image_bytes)
            if ctx.event is not None and hasattr(ctx.bot, "send"):
                await ctx.bot.send(ctx.event, image_message)
            else:
                await ctx.bot.call_api("send_group_msg", group_id=int(ctx.group_id), message=image_message)
            sent += 1
        except Exception:
            # Keep unsent emoji queued for logging/debug visibility, but do not
            # break the main reply after it has already been delivered.
            remaining.append(item)
    ctx.extra["pending_mood_emojis"] = remaining
    return sent


async def send_mood_emoji(
    ctx: ToolContext,
    reaction: str = "",
    intensity: str = "medium",
    stance: str = "shared_with_user",
    topic: str = "general",
    emoji_name: str = "",
    reason_code: str = "",
    mood: str = "",
    reason: str = "",
) -> str:
    if ctx.bot is None:
        return "当前没有可用 bot，无法发送表情。"

    asset = choose_emoji_asset(
        mood=mood,
        emoji_name=emoji_name,
        reaction=reaction,
        intensity=intensity,
        stance=stance,
        topic=topic,
        reason_code=reason_code,
        request_id=str(getattr(ctx, "request_id", "") or ""),
        group_id=ctx.group_id,
    )
    if asset is None:
        return "没有找到可用表情包，请检查表情包目录。"

    path = Path(asset["path"])
    if path.stat().st_size > MAX_EMOJI_BYTES:
        return "表情文件过大，已取消发送：{0}".format(asset["name"])

    ctx.extra = dict(ctx.extra or {})
    pending = list(ctx.extra.get("pending_mood_emojis") or [])
    pending.append({"name": asset["name"], "path": str(path)})
    ctx.extra["pending_mood_emojis"] = pending

    detail_text = reason or reason_code
    detail = "，理由：{0}".format(detail_text) if detail_text else ""
    return (
        "已准备在主回复之后向当前群 {0} 发送表情：{1}{2}。"
        "如果这个表情已经完整表达回复，最终只输出 [NO_REPLY]，不要再补充文字。"
    ).format(ctx.group_id, asset["name"], detail)


def register_tools() -> None:
    ensure_tool(ToolSpec(
        name="send_like",
        description="给当前用户或指定 QQ 用户点赞。会改变 QQ 状态，必须用户确认后执行。",
        parameters={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "目标 QQ 号，默认当前用户"},
                "times": {"type": "integer", "description": "点赞次数，最多 10", "default": 1},
            },
            "required": [],
        },
        handler=send_like,
        permission="confirm_write",
        category="qq_actions",
        timeout_seconds=20.0,
    ))
    ensure_tool(ToolSpec(
        name="send_group_message",
        description="Send a message to the current or specified QQ group. Requires explicit confirmation.",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message content to send"},
                "group_id": {"type": "string", "description": "Target group id, defaults to current group"},
            },
            "required": ["message"],
        },
        handler=send_group_message,
        permission="confirm_write",
        category="qq_actions",
        timeout_seconds=20.0,
    ))
    ensure_tool(ToolSpec(
        name="send_mood_emoji",
        description=(
            "根据当前回复的反应意图，从本地表情包白名单中选择并发送一个表情到当前会话。"
            "只能发送表情包目录内的图片，不能指定其他群或任意文件路径。"
            "优先使用 reaction/intensity/stance/topic；mood 仅用于兼容旧参数。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "reaction": {
                    "type": "string",
                    "description": "反应类型，例如 celebration、approval、amused、skeptical、frustrated、sad；不确定可留空",
                },
                "intensity": {
                    "type": "string",
                    "description": "强度：low、medium、high",
                },
                "stance": {
                    "type": "string",
                    "description": "立场：shared_with_user、toward_user、toward_event、toward_claim",
                },
                "topic": {
                    "type": "string",
                    "description": "主题：general、football、football_news、meme、injury、transfer、match 等",
                },
                "mood": {
                    "type": "string",
                    "description": "兼容旧参数：positive_neutral 或 negative；新调用不要主动填写",
                },
                "emoji_name": {
                    "type": "string",
                    "description": "可选：指定白名单内的表情素材名；不能是路径",
                },
                "reason_code": {
                    "type": "string",
                    "description": "可选：规则原因码，trace 只记录参数名",
                },
                "reason": {
                    "type": "string",
                    "description": "兼容旧参数：为什么此时适合发表情，简短填写",
                },
            },
            "required": [],
        },
        handler=send_mood_emoji,
        permission="safe_write",
        category="qq_actions",
        timeout_seconds=20.0,
    ))
