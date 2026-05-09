"""阿森纳周报 - 每周一自动爬取新闻 + 知识库注入 + 群发"""

import nonebot
from nonebot import on_command, get_driver
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from nonebot_plugin_apscheduler import scheduler
import httpx
import asyncio
import logging
import os
import re
from typing import Optional
from datetime import datetime, date
from plugins.arteta_render import text_to_tactical_board
from plugins.arteta_knowledge import clear_cache

logger = logging.getLogger(__name__)

# --- 1. 配置 ---
driver = get_driver()
try:
    config = driver.config.model_dump()
except AttributeError:
    config = driver.config.dict()

DEEPSEEK_API_KEY = str(config.get("deepseek_api_key", "")).strip('"\'')
WEEKLY_NEWS_ENABLED = str(config.get("weekly_news_enabled", "true")).lower() in ("true", "1", "yes")
ADMIN_QQ = "2648955710"
KNOWLEDGE_BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge_base")

# --- 2. 新闻源配置 ---
SOURCES = {
    "bbc": {
        "url": "https://www.bbc.com/sport/football/teams/arsenal",
        "label": "BBC Sport",
    },
    "sky": {
        "url": "https://www.skysports.com/arsenal",
        "label": "Sky Sports",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
}

WEEKLY_PROMPT = """你是阿尔特塔，阿森纳主教练。请根据以下本周足球新闻，生成一份给球员看的更衣室周报。

要求：
1. 每条新闻用 [red]（阿森纳相关）或 [blue]（其他）标记
2. 语气激情、直接、像在更衣室里讲话
3. 对阿森纳表现给出你的真实评价
4. 对争冠对手的动向也要有所点评
5. 首行用"本周要点"作为标题
6. 每条新闻一行，简洁有力，不要列清单

本周新闻：
{articles}"""


# ===== 新闻抓取 =====

async def fetch_bbc_news() -> list:
    """抓取 BBC Sport Arsenal 页面，提取新闻标题和链接"""
    results = []
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            resp = await client.get(SOURCES["bbc"]["url"], headers=HEADERS, follow_redirects=True)
            if resp.status_code != 200:
                logger.warning(f"[WeeklyNews] BBC 返回状态码 {resp.status_code}")
                return results

            html = resp.text
            articles = re.findall(
                r'<a[^>]*href="(/sport/football[^"]+)"[^>]*>(.*?)</a>',
                html, re.DOTALL
            )
            seen = set()
            for href, text in articles:
                title = re.sub(r'<[^>]+>', '', text).strip()
                title = re.sub(r'\s+', ' ', title)
                full_url = f"https://www.bbc.com{href}" if href.startswith("/") else href
                if title and len(title) > 15 and title not in seen:
                    seen.add(title)
                    results.append((title, full_url))

            logger.info(f"[WeeklyNews] BBC 源抓取到 {len(results)} 条新闻")
    except Exception as e:
        logger.warning(f"[WeeklyNews] BBC 抓取异常: {e}")

    return results


async def fetch_sky_news() -> list:
    """抓取 Sky Sports Arsenal 页面，提取新闻标题和链接"""
    results = []
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            resp = await client.get(SOURCES["sky"]["url"], headers=HEADERS, follow_redirects=True)
            if resp.status_code != 200:
                logger.warning(f"[WeeklyNews] Sky 返回状态码 {resp.status_code}")
                return results

            html = resp.text
            articles = re.findall(r'<h3[^>]*>(.*?)</h3>', html, re.DOTALL)
            for a in articles:
                link = re.search(r'<a[^>]*href="(/football/news/[^"]+)"[^>]*>(.*?)</a>', a, re.DOTALL)
                if link:
                    title = re.sub(r'<[^>]+>', '', link.group(2)).strip()
                    title = re.sub(r'\s+', ' ', title)
                    href = link.group(1)
                    if title and len(title) > 15:
                        full_url = f"https://www.skysports.com{href}"
                        results.append((title, full_url))

            logger.info(f"[WeeklyNews] Sky 源抓取到 {len(results)} 条新闻")
    except Exception as e:
        logger.warning(f"[WeeklyNews] Sky 抓取异常: {e}")

    return results


async def fetch_article_content(url: str) -> str:
    """打开新闻正文页，提取 <p> 标签文本，最多 500 字"""
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            resp = await client.get(url, headers=HEADERS, follow_redirects=True)
            if resp.status_code != 200:
                return ""

            html = resp.text
            paragraphs = re.findall(r'<p>(.*?)</p>', html, re.DOTALL)
            content = []
            total_len = 0
            for p in paragraphs:
                text = re.sub(r'<[^>]+>', '', p).strip()
                text = re.sub(r'\s+', ' ', text)
                if text and len(text) > 30:
                    content.append(text)
                    total_len += len(text)
                    if total_len >= 500:
                        break
            return "\n".join(content)
    except Exception as e:
        logger.warning(f"[WeeklyNews] 正文抓取失败 {url[:50]}: {e}")
        return ""


async def fetch_arsenal_news() -> list:
    """从所有源抓取新闻，去重合并，返回 Top 5"""
    bbc_task = fetch_bbc_news()
    sky_task = fetch_sky_news()
    bbc_results, sky_results = await asyncio.gather(bbc_task, sky_task, return_exceptions=True)

    if isinstance(bbc_results, Exception):
        bbc_results = []
    if isinstance(sky_results, Exception):
        sky_results = []

    # 去重合并（标题前20字去重）
    seen_titles = set()
    merged = []
    for title, url in bbc_results + sky_results:
        key = title[:20]
        if key not in seen_titles:
            seen_titles.add(key)
            merged.append((title, url))

    # 按标题长度排序（长标题通常信息更丰富）
    merged.sort(key=lambda x: len(x[0]), reverse=True)
    top5 = merged[:5]
    logger.info(f"[WeeklyNews] 合并后 {len(merged)} 条，选取 Top {len(top5)}")
    return top5


# ===== LLM 周报生成 =====

async def generate_weekly_report(articles: list) -> str:
    """调用 DeepSeek 生成阿尔特塔风格周报"""
    if not articles or not DEEPSEEK_API_KEY:
        return ""

    # 构建文章输入
    article_lines = []
    for i, (title, url) in enumerate(articles, 1):
        content = await fetch_article_content(url)
        article_lines.append(f"{i}. 【{title}】")
        if content:
            article_lines.append(f"   {content[:300]}")
        else:
            article_lines.append(f"   （正文获取失败）")
    articles_text = "\n".join(article_lines)

    prompt = WEEKLY_PROMPT.format(articles=articles_text)

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
                        "max_tokens": 1500,
                    },
                )
                if resp.status_code == 200:
                    report = resp.json()["choices"][0]["message"]["content"].strip()
                    logger.info(f"[WeeklyNews] LLM 周报生成成功")
                    return report
                else:
                    logger.warning(f"[WeeklyNews] API 失败 (尝试 {attempt+1}/2): {resp.status_code}")
                    if attempt == 0:
                        await asyncio.sleep(3)
        except Exception as e:
            logger.warning(f"[WeeklyNews] API 异常 (尝试 {attempt+1}/2): {e}")
            if attempt == 0:
                await asyncio.sleep(3)

    return ""


# ===== 知识库注入 =====

def save_to_knowledge_base(report: str) -> bool:
    """将周报写入 knowledge_base/weekly-news.md"""
    if not report:
        return False
    try:
        today = date.today()
        week_num = today.isocalendar()[1]
        content = (
            f"# 阿森纳周报 ({today.year}年第{week_num}周)\n\n"
            f"> 生成时间：{today.isoformat()} 09:00\n\n"
            f"## 本周新闻\n{report}\n"
        )
        os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)
        path = os.path.join(KNOWLEDGE_BASE_DIR, "weekly-news.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"[WeeklyNews] 已更新知识库 {path}")
        return True
    except Exception as e:
        logger.error(f"[WeeklyNews] 知识库写入失败: {e}")
        return False


# ===== 群发布 =====

async def _run_weekly_pipeline() -> Optional[str]:
    """运行完整周报管道：获取 → 生成 → 保存 → 发布。失败返回 None。"""
    articles = await fetch_arsenal_news()
    if not articles:
        logger.warning("[WeeklyNews] 无可用新闻，跳过")
        return None

    report = await generate_weekly_report(articles)
    if not report:
        logger.warning("[WeeklyNews] 周报生成失败，跳过")
        return None

    save_to_knowledge_base(report)
    clear_cache()
    await publish_to_groups(report)
    return report


async def publish_to_groups(report: str):
    """渲染周报为图片并发送到所有群"""
    if not report:
        return

    bots = nonebot.get_bots()
    if not bots:
        logger.warning("[WeeklyNews] 无可用 bot 实例")
        return

    today = date.today()
    day_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    day_name = day_names[today.weekday()]
    date_str = today.strftime("%Y年%m月%d日")

    final_text = (
        f"[red]阿尔特塔的更衣室周报[/red]\n"
        f"[blue]{date_str} {day_name}[/blue]\n\n"
        f"{report}"
    )

    group_list = []
    for bot in bots.values():
        try:
            group_list = await bot.call_api("get_group_list")
        except Exception as e:
            logger.error(f"[WeeklyNews] bot 获取群列表异常: {e}")

    try:
        img_bytes = text_to_tactical_board(final_text)
        for bot in bots.values():
            for group in group_list:
                gid = group["group_id"]
                try:
                    await bot.call_api(
                        "send_group_msg",
                        group_id=gid,
                        message=MessageSegment.image(img_bytes),
                    )
                    logger.info(f"[WeeklyNews] 已发送群 {gid}")
                except Exception as e:
                    logger.warning(f"[WeeklyNews] 群 {gid} 发送失败: {e}")
    except Exception as e:
        logger.error(f"[WeeklyNews] 图片渲染失败: {e}，尝试发送纯文本")
        plain_text = final_text.replace('[red]', '').replace('[/red]', '') \
                               .replace('[blue]', '').replace('[/blue]', '') \
                               .replace('*', '').strip()
        for bot in bots.values():
            for group in group_list:
                try:
                    await bot.call_api(
                        "send_group_msg",
                        group_id=group["group_id"],
                        message=plain_text[:2000],
                    )
                except Exception as e2:
                    logger.warning(f"[WeeklyNews] 群文本发送也失败: {e2}")


# ===== 定时任务 =====

@scheduler.scheduled_job(
    "cron", day_of_week="mon", hour=9, minute=0, id="weekly_news", misfire_grace_time=300
)
async def weekly_news_job():
    if not WEEKLY_NEWS_ENABLED:
        logger.info("[WeeklyNews] 周报功能已禁用")
        return

    logger.info("[WeeklyNews] 开始周报生成")
    await _run_weekly_pipeline()
    logger.info("[WeeklyNews] 周报生成完成")


# ===== 手动触发命令 =====

weekly_cmd = on_command("周报", aliases={"weekly", "weeklynews"}, priority=5, block=True)


@weekly_cmd.handle()
async def handle_weekly_manual(bot: Bot, event: GroupMessageEvent):
    user_id = event.get_user_id()
    if str(user_id) != ADMIN_QQ:
        await weekly_cmd.finish("只有教练组可以手动发布周报！")

    await weekly_cmd.send("🔄 开始爬取新闻生成周报，请稍候...")

    result = await _run_weekly_pipeline()
    if result:
        await weekly_cmd.finish("✅ 周报已生成并发布到所有群！")
    else:
        await weekly_cmd.finish("周报生成失败，请检查日志。")
