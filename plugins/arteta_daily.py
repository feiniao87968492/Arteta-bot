"""每日群聊总结 - 阿尔特塔的更衣室日报

功能：
- 记录所有群消息到 daily_messages 表
- 每天 22:30 自动发布当日群聊总结（阿尔特塔风格）
- 手动触发: /今日总结
- 自动清理 7 天前的消息记录
"""
import nonebot
from nonebot import on_message, on_command, get_driver
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from nonebot_plugin_apscheduler import scheduler
import sqlite3
import aiosqlite
import httpx
import time
import asyncio
import logging
from datetime import datetime, date
from plugins.arteta_render import text_to_tactical_board

logger = logging.getLogger(__name__)

DB_PATH = "arsenal_data.db"
ADMIN_QQ = "2648955710"

# --- 1. 初始化数据库 ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS daily_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        group_id TEXT NOT NULL,
        nickname TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL,
        timestamp INTEGER NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_ts ON daily_messages(group_id, timestamp)")
    conn.commit()
    conn.close()

init_db()

# --- 2. 配置 ---
driver = get_driver()
try:
    config = driver.config.model_dump()
except AttributeError:
    config = driver.config.dict()

DEEPSEEK_API_KEY = str(config.get("deepseek_api_key", "")).strip('"\'')
SUMMARY_ENABLED = str(config.get("daily_summary_enabled", "true")).lower() in ("true", "1", "yes")

# --- 3. 消息记录器：捕获所有群消息 ---
# 优先级1确保在所有命令处理器之前运行（命令处理器 priority=3~11 且 block=True）
record_all = on_message(priority=1, block=False)


@record_all.handle()
async def record_message(bot: Bot, event: GroupMessageEvent):
    text = event.get_message().extract_plain_text().strip()
    if not text:
        return

    user_id = event.get_user_id()
    group_id = str(event.group_id)
    nickname = event.sender.card or event.sender.nickname or ""
    now = int(time.time())

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO daily_messages (user_id, group_id, nickname, message, timestamp) VALUES (?, ?, ?, ?, ?)",
                (user_id, group_id, nickname, text, now),
            )
            await db.commit()
    except Exception as e:
        logger.error(f"[DailySummary] 保存消息失败: {e}")


# --- 4. DeepSeek 总结生成 ---
SUMMARY_PROMPT = """你是阿尔特塔，阿森纳主教练。现在是晚上，你在更衣室里对球员们做今天训练和聊天的总结。
以下是今天群里聊天记录（按时间排序）。

要求：
1. 点名最活跃的几名球员，点评他们的热情和表现
2. 提到今天聊的主要话题、热点
3. 语气要像在更衣室里讲话——激情、直接、有感染力
4. 控制在 300-500 字
5. 使用 [red] 和 [/red] 标记阿森纳相关内容，[blue] 和 [/blue] 标记其他内容
6. 最后用一句激励的话收尾
7. 不要列数据清单，用自然的段落表达

今日聊天记录：
{chat_log}

【统计数据】
总消息数：{total_msgs} 条
发言人数：{active_users} 人
最活跃球员：{top_users_str}

请输出你的总结："""


async def generate_summary(messages: list) -> str:
    """调用 DeepSeek 生成群聊总结"""
    if not messages or not DEEPSEEK_API_KEY:
        return None

    # 构建聊天记录文本
    chat_lines = []
    for nick, msg, ts in messages:
        time_str = datetime.fromtimestamp(ts).strftime("%H:%M")
        chat_lines.append(f"[{time_str}] {nick}: {msg}")
    chat_log = "\n".join(chat_lines)

    # 统计
    total_msgs = len(messages)
    user_counts = {}
    for nick, _msg, _ts in messages:
        user_counts[nick] = user_counts.get(nick, 0) + 1

    active_users = len(user_counts)
    top_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_users_str = "、".join(f"{nick}({count}条)" for nick, count in top_users)

    prompt = SUMMARY_PROMPT.format(
        chat_log=chat_log[-4000:],  # 截断避免超 token
        total_msgs=total_msgs,
        active_users=active_users,
        top_users_str=top_users_str,
    )

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                    json={
                        "model": "deepseek-v4-flash",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.7,
                        "max_tokens": 1000,
                    },
                )
                if resp.status_code == 200:
                    summary = resp.json()["choices"][0]["message"]["content"].strip()
                    return summary
                else:
                    logger.warning(
                        f"[DailySummary] API 失败 (尝试 {attempt+1}/2): {resp.status_code}"
                    )
                    if attempt == 0:
                        await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"[DailySummary] API 异常 (尝试 {attempt+1}/2): {e}")
            if attempt == 0:
                await asyncio.sleep(2)

    return None


# --- 5. 定时任务：22:30 发布总结 ---
@scheduler.scheduled_job(
    "cron", hour=22, minute=30, id="daily_summary", misfire_grace_time=300
)
async def daily_summary_job():
    if not SUMMARY_ENABLED:
        logger.info("[DailySummary] 每日总结已禁用")
        return

    bots = nonebot.get_bots()
    if not bots:
        logger.warning("[DailySummary] 无可用 bot 实例")
        return

    today = date.today()
    today_start = int(datetime(today.year, today.month, today.day).timestamp())
    today_end = today_start + 86400

    # 获取当日有消息的所有群
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT DISTINCT group_id FROM daily_messages WHERE timestamp >= ? AND timestamp < ?",
                (today_start, today_end),
            ) as cursor:
                groups = [row[0] for row in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"[DailySummary] 查询群列表失败: {e}")
        return

    if not groups:
        logger.info("[DailySummary] 今日无消息，跳过总结")
        return

    date_str = today.strftime("%Y年%m月%d日")
    day_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    day_name = day_names[today.weekday()]

    for bot in bots.values():
        for group_id in groups:
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute(
                        """SELECT nickname, message, timestamp FROM daily_messages
                           WHERE group_id = ? AND timestamp >= ? AND timestamp < ?
                           ORDER BY timestamp ASC""",
                        (group_id, today_start, today_end),
                    ) as cursor:
                        messages = await cursor.fetchall()

                if not messages:
                    continue

                summary_text = await generate_summary(messages)
                if not summary_text:
                    continue

                final_text = (
                    f"[red]阿尔特塔的更衣室日报[/red]\n"
                    f"[blue]{date_str} {day_name}[/blue]\n\n"
                    f"{summary_text}"
                )

                try:
                    img_bytes = text_to_tactical_board(final_text)
                    await bot.send_group_msg(
                        group_id=int(group_id),
                        message=MessageSegment.image(img_bytes),
                    )
                    logger.info(f"[DailySummary] ✅ 已发送群 {group_id} 的每日总结")
                except Exception as e:
                    logger.warning(f"[DailySummary] 图片渲染失败，尝试文字发送: {e}")
                    await bot.send_group_msg(
                        group_id=int(group_id), message=final_text
                    )

            except Exception as e:
                logger.error(f"[DailySummary] 群 {group_id} 总结发送失败: {e}")

    # --- 数据清理：删除7天前的记录 ---
    try:
        week_ago = today_start - 7 * 86400
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM daily_messages WHERE timestamp < ?", (week_ago,))
            await db.commit()
        logger.info("[DailySummary] ✅ 已清理 7 天前的消息记录")
    except Exception as e:
        logger.error(f"[DailySummary] 数据清理失败: {e}")


# --- 6. 手动触发指令（管理员调试用） ---
manual_cmd = on_command("今日总结", aliases={"日报", "daily"}, priority=5, block=True)


@manual_cmd.handle()
async def handle_manual_summary(bot: Bot, event: GroupMessageEvent):
    user_id = event.get_user_id()
    if str(user_id) != ADMIN_QQ:
        await manual_cmd.finish("只有教练组可以手动发布总结！")

    today = date.today()
    today_start = int(datetime(today.year, today.month, today.day).timestamp())
    today_end = today_start + 86400
    group_id = str(event.group_id)

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                """SELECT nickname, message, timestamp FROM daily_messages
                   WHERE group_id = ? AND timestamp >= ? AND timestamp < ?
                   ORDER BY timestamp ASC""",
                (group_id, today_start, today_end),
            ) as cursor:
                messages = await cursor.fetchall()
    except Exception as e:
        await manual_cmd.finish(f"查询消息失败：{e}")
        return

    if not messages:
        await manual_cmd.finish("今天群里还没人说话呢，让球员们热起来！")
        return

    summary_text = await generate_summary(messages)
    if not summary_text:
        await manual_cmd.finish("总结生成失败（API 可能暂时离线）")
        return

    date_str = today.strftime("%Y年%m月%d日")
    day_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    day_name = day_names[today.weekday()]
    final_text = (
        f"[red]阿尔特塔的更衣室日报[/red]\n"
        f"[blue]{date_str} {day_name}[/blue]\n\n"
        f"{summary_text}"
    )

    try:
        img_bytes = text_to_tactical_board(final_text)
        await bot.call_api("send_group_msg", group_id=int(group_id), message=MessageSegment.image(img_bytes))
    except Exception:
        await bot.call_api("send_group_msg", group_id=int(group_id), message=final_text)

    await manual_cmd.finish()
