# plugins/arteta_admin.py
import nonebot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
import aiosqlite

# --- 球队纪律委员会配置 ---
DB_PATH = "arsenal_data.db"
ADMIN_QQ = "2648955710"  # 主教练特权账号

# 注册指令
ban_cmd = on_command("下放", aliases={"禁言", "红牌"}, priority=3, block=True)

@ban_cmd.handle()
async def handle_ban(bot: Bot, event: GroupMessageEvent):
    # 1. 权限核验
    if str(event.user_id) != ADMIN_QQ:
        await ban_cmd.finish("你没有权限干涉球队阵容！")
        return

    # 2. 战术识别：寻找消息里被艾特(@)的球员
    msg = event.get_message()
    target_qq = None
    for seg in msg:
        if seg.type == "at":
            target_qq = str(seg.data.get("qq"))
            break

    if not target_qq:
        await ban_cmd.finish("你需要明确艾特出要下放的球员！")
        return

    # 3. 执行下放惩罚
    try:
        # 禁言 10 分钟
        await bot.set_group_ban(group_id=event.group_id, user_id=int(target_qq), duration=600)
        
        # 联动扣除信任度
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''UPDATE players SET favorability = favorability - 10 WHERE user_id = ? AND group_id = ?''', (target_qq, str(event.group_id)))
            await db.commit()
            
    except Exception as e:
        # 如果报错（比如不是管理员），在这里拦截并提示
        await ban_cmd.finish(f"下放失败。我是不是还没被任命为群管理员？({str(e)})")
        return

    # 只有成功才会走到这里，不再有任何缩进和后续代码
    await ban_cmd.finish(f"执行纪律：已将该球员下放预备队反省10分钟，并扣除10点信任度！")