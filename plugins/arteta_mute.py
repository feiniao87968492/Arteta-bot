# plugins/arteta_mute.py
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from typing import Dict
from loguru import logger

# 全局群静音状态（内存，重启重置）
muted_groups: Dict[str, bool] = {}


def is_muted(group_id: str) -> bool:
    """供 arteta_chat 调用的静音检查"""
    return muted_groups.get(group_id, False)


mute_cmd = on_command("塔闭嘴", priority=5, block=True)


@mute_cmd.handle()
async def handle_mute(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    if muted_groups.get(group_id):
        await mute_cmd.finish("我已经闭嘴了，别喊了。")
    muted_groups[group_id] = True
    logger.info(f"[Mute] 群 {group_id} 已闭嘴")
    await mute_cmd.finish("好的，我闭嘴了。")


unmute_cmd = on_command("塔说话", priority=5, block=True)


@unmute_cmd.handle()
async def handle_unmute(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    if not muted_groups.get(group_id):
        await unmute_cmd.finish("我不是正在说着吗？")
    muted_groups[group_id] = False
    logger.info(f"[Mute] 群 {group_id} 恢复说话")
    await unmute_cmd.finish("我回来了。")
