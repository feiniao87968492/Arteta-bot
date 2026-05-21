# plugins/arteta_like.py
"""QQ 名片赞功能 - 赞我"""

import random
import sqlite3
from datetime import date

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.exception import FinishedException

DB_PATH = __import__("os").environ.get("ARTETA_DB_PATH", "arsenal_data.db")
MAX_NORMAL = 10  # 普通用户每日上限
MAX_VIP = 50     # 会员用户每日上限


def _init_table():
    """确保 daily_likes 表存在"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS daily_likes (
        user_id TEXT NOT NULL,
        like_date TEXT NOT NULL,
        count INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, like_date)
    )""")
    conn.commit()
    conn.close()


def _get_count(user_id: str) -> int:
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT count FROM daily_likes WHERE user_id=? AND like_date=?",
        (user_id, today)
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def _add_count(user_id: str, n: int):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT INTO daily_likes (user_id, like_date, count) VALUES (?, ?, ?)
        ON CONFLICT(user_id, like_date) DO UPDATE SET count = count + ?""",
        (user_id, today, n, n))
    conn.commit()
    conn.close()


def get_daily_like_limit(is_vip: bool) -> int:
    """返回用户每日名片赞上限。"""
    return MAX_VIP if is_vip else MAX_NORMAL


_init_table()

like_cmd = on_command("赞我", aliases={"点赞我", "like_me"}, priority=5, block=True)


@like_cmd.handle()
async def handle_like_me(bot: Bot, event: GroupMessageEvent):
    user_id = event.get_user_id()

    # --- 检测是否会员 ---
    is_vip = False
    try:
        info = await bot.call_api("get_group_member_info", group_id=event.group_id, user_id=int(user_id), no_cache=True)
        # NapCat 扩展字段：is_vip / vip_level
        if info.get("is_vip") or info.get("vip_level", 0) > 0:
            is_vip = True
    except Exception:
        pass
    # 群管理员 / 群主赠送 VIP 待遇
    if not is_vip and event.sender.role in ("owner", "admin"):
        is_vip = True

    max_likes = get_daily_like_limit(is_vip)
    current = _get_count(user_id)
    if current >= max_likes:
        already_done = [
            "你今天已经够闪耀了，留点机会给队友吧。明天训练早点到。",
            "赞过了，别贪心。真正的领袖不需要天天被点赞。",
            "今天的额度用完了，留着那股劲去场上拼吧。",
            "你的油箱今天已经加满了，明天再来。",
            "再点下去别人该说我偏心了。去跑两圈冷静一下。",
            "点赞不能当饭吃，去训练场上证明自己。",
        ]
        await bot.send(event, f"【阿尔特塔】{random.choice(already_done)}（{current}/{max_likes}）")
        await FinishedException()
        return

    remaining = max_likes - current

    # --- 发送点赞 ---
    liked = 0
    try:
        if hasattr(bot, "send_like"):
            # 部分适配器有专用方法
            for _ in range(remaining):
                await bot.send_like(user_id=int(user_id))
                liked += 1
        else:
            # 通用 OneBot V11 扩展 API：send_like（go-cqhttp / NapCat）
            resp = await bot.call_api("send_like", user_id=int(user_id), times=remaining)
            liked = remaining
            if isinstance(resp, dict):
                liked = resp.get("liked", remaining)
    except Exception as e:
        err = str(e)
        if "not implemented" in err.lower() or "unsupported action" in err.lower() or "10002" in err:
            await bot.send(event, "【阿尔特塔】当前 QQ 协议不支持点赞功能（send_like），请联系管理员检查 NapCat 版本。")
            await FinishedException()
            return
        # 部分实现会返回实际点赞数
        liked = remaining
        # 如果第一下就失败了，回退逐个点赞
        if remaining == max_likes:
            try:
                liked = 0
                for i in range(remaining):
                    try:
                        await bot.call_api("send_like", user_id=int(user_id), times=1)
                        liked += 1
                    except Exception:
                        break
            except Exception:
                pass

    if liked > 0:
        _add_count(user_id, liked)
        suffix = "（会员×50）" if is_vip else ""
        # 阿尔特塔式点赞语录
        cheers = [
            "这跑位，值一个赞！去跑几个折返跑庆祝一下。",
            "不错，继续用这种能量影响比赛！",
            "你在场上的每一分钟都在为这件球衣而战。继续保持！",
            "这就是我想看到的态度——每一球都拼到底。",
            "好样的，你证明了为什么你配得上这件红白战袍。",
            "这种投入度，正是我们需要的。加油！",
            "我喜欢你今天的比赛方式。继续前进！",
            "这就是阿森纳的标准——永不满足，永远要更多。",
            "你的能量感染了整个球队。保持下去！",
            "靠你了！每一场都要拿出这种表现。",
            "这是你应得的。继续保持饥饿感！",
            "真正的枪手从不满足——你今天做得不错，但明天要更好。",
            "继续保持这种专注度，你就是球队不可或缺的一部分。",
        ]
        line = random.choice(cheers)
        msg = f"【阿尔特塔】{line}{suffix}"
        if liked > 1:
            msg += f"（已点赞 {liked} 次）"
        await bot.send(event, msg)
