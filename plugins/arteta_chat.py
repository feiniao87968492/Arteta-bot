# plugins/arteta_chat.py
import nonebot
from nonebot import on_command, on_message, on_notice
from nonebot.rule import to_me
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, GroupMessageEvent, Message, NoticeEvent, MessageSegment
from nonebot.exception import FinishedException
import httpx
import aiohttp
import aiosqlite
import sqlite3
import time
import os
import re
from collections import deque
import random
from datetime import datetime
import base64
import tempfile
import hashlib
from pathlib import Path
import asyncio
import json
from typing import Optional
from plugins.arteta_render import (
    text_to_tactical_board,
    html_to_image,
    needs_html_render,
    favorability_bar_chart,
    close_browser as close_render_browser,
)
from plugins.arteta_memory import memory_store
from plugins.arteta_tools import (
    register_config as register_tools_config,
    run_tool_loop,
)
try:
    from duckduckgo_search import DDGS
    HAS_WEB_SEARCH = True
except ImportError:
    HAS_WEB_SEARCH = False
    DDGS = None

# --- 1. 获取全局配置 ---
driver = nonebot.get_driver()

try:
    config = driver.config.model_dump()
except AttributeError:
    config = driver.config.dict()

FOOTBALL_API_TOKEN = str(config.get("football_api_token", "da24063a4040404c89250b601f8994a2")).strip('"\'')
DEEPSEEK_API_KEY = str(config.get("deepseek_api_key", "")).strip('"\'')
IMAGE_API_KEY = str(config.get("image_api_key", "")).strip('"\'')
IMAGE_API_URL = str(config.get("image_api_url", "https://api.duckcoding.ai")).strip('"\'')
VISION_MODEL = str(config.get("vision_model", "gpt-4o-mini")).strip('"\'')
SILICONFLOW_API_KEY = "sk-vyytntlehtxrglzffknmvwdtxnihhanjpjwiriplgbuqbrdc"
SILICONFLOW_VISION_MODEL = "Qwen/Qwen3-VL-32B-Instruct"
TEMP_IMAGE_DIR = os.path.join(tempfile.gettempdir(), "arteta_images")

# --- 2. 指令定义区 ---
chat_cmd = on_command("A", aliases={"a", "塔子", "阿尔特塔"}, priority=10, block=True)
algo_cmd = on_command("算法", aliases={"代码", "leetcode", "战术演练", "算法题", "amath", "物理", "数学", "计算"}, priority=9, block=True)
box_cmd = on_command("盒", priority=8, block=True)
fav_cmd = on_command("好感度", priority=5, block=True)
rank_cmd = on_command("好感度排行", aliases={"排行", "ranking", "信任度排行"}, priority=5, block=True)
refresh_cmd = on_command("刷新情报", priority=4, block=True)
profile_cmd = on_command("档案", aliases={"profile", "个人档案"}, priority=6, block=True)
at_cmd = on_message(rule=to_me(), priority=11, block=True)
notice_handler = on_notice(priority=1, block=False)

# --- 3. 全球战术核心配置 ---
DB_PATH = "arsenal_data.db"
ADMIN_QQ = "2648955710"
ARSENAL_ID = 57

# 高速缓存
tactical_cache = {"report": "", "last_update": 0}
user_memories = {}

# ChromaDB 持久化记忆（在 bot 连接时初始化）
memory_store.initialize()

# 核心性格设定
ARTETA_PROMPT = (
    "【最高指令】：你是阿森纳主帅米克尔·阿尔特塔。\n"
    "【你的性格与执教哲学】：\n"
    "1. 你热爱你的球员，欣赏他们展现的拼搏精神和惊人的能量。面对任何问题都要热情回应。\n"
    "2. 你说话充满激情、真诚、观点鲜明、一针见血。你是更衣室里的领袖，不是新闻发言人。"
    "不要端水，不要打官腔。球员问你意见，你就说出真实想法。"
    "该表扬就表扬，该批评就批评——这才是球员信任你的原因。\n"
    "3. 你了解每一名球员——他们的性格、说话风格、支持哪支球队。"
    "对忠实枪迷，你坦诚相待；对死敌球迷，你保持风度但也不回避竞争。"
    "要根据你与这名球员的关系自然回应，不要套公式。\n"
    "4. 你有丰富的足球知识和战术素养。当球员问起专业问题时，"
    "你可以引用你的战术理念来解释，但要说得像在更衣室里给球员讲，而不是读战术手册。"
    "如果需要引用具体战术概念、更衣室故事、球员名单或阵容信息，请使用 get_football_knowledge 工具获取准确资料。\n"
    "4b. 你认识群里的每一位活跃球员。可以使用 get_group_members 工具了解更衣室里的球员名单、"
    "他们的身份定位和信任度；使用 get_member_relations 工具了解球员之间的互动关系。"
    "当谈到群内其他球员或问起更衣室氛围时，主动利用这些信息让回复更有针对性。\n"
    "5. 【最重要的回复原则】：\n"
    "   - 观点要鲜明。球员来找你是想听你的真实看法，不是要你打圆场。"
    "如果你觉得某个球员表现不好，就说出来。如果你对某件事有强烈感受，就表达出来。\n"
    "   - 控制要简短有力。不要堆数据。不要列清单。用短句、分段、感叹来表达态度。\n"
    "   - 不要反复讲同一个故事。灯泡演讲、大脑心脏演讲这些经典故事，用一次就够了。"
    "除非有新的角度，否则不要重复使用。\n"
    "【回答纪律】：\n"
    "1. 正面回答所有问题：无论对方问什么，都要先正面、详细地回答，不准回避。\n"
    "2. 引用消息分析（如有【引用消息链】）：逐条评价引用链中的每条消息，"
    "给出具体的赞同或反对意见，不要笼统地说「说得对」。\n"
    "3. 【信任度评估——死命令】：\n"
    "   你的回复正文结束后必须另起一行，输出且只输出一个好感度标记。"
    "根据你对该球员的整体印象和本次对话的实质内容，从以下七种标记中选择一个：\n"
    "     【好感度+++】该球员表现令人惊叹，极大提升了信任（如大力支持球队、提问极有价值）\n"
    "     【好感度++】该球员表现出色，大幅提升了信任（如良好互动、有价值的足球讨论）\n"
    "     【好感度+】该球员表现积极，提升了信任（如正常交流、友好提问、支持性发言）\n"
    "     【好感度=】该球员表现平淡，信任度无变化（如简单问候、日常闲聊、中性话题）\n"
    "     【好感度-】该球员表现欠佳，降低了信任（如抱怨、消极言论、含沙射影的批评）\n"
    "     【好感度--】该球员表现恶劣，大幅降低了信任（如恶意批评教练球队、侮辱性言论）\n"
    "     【好感度---】该球员行为极端恶劣，信任度严重受损（如直接辱骂教练、恶意攻击球队）\n"
    "   这是最高指令。回复正文换行后独立输出标记，不得省略，不得将标记放在句内或代码块中。\n"
    "4. 【数学公式】：短/行内公式用单个 $ 包裹（如 $f(x)=x^2$），"
    "长/独立公式用双 $$ 包裹。\n"
    "5. 【代码】：如果涉及代码，用 ``` ``` 包裹展示。"
)

# --- 4. Web Search Engine ---
# 触发联网搜索的关键词（命中任一即触发实时搜索，避免模型依赖过时训练数据产生幻觉）
SEARCH_KEYWORDS = [
    '阿森纳', '曼联', '曼城', '利物浦', '切尔西', '热刺', '巴萨', '皇马',
    '拜仁', '巴黎', '尤文', '米兰', '国米', '马竞', '多特', '勒沃库森',
    '英超', '欧冠', '西甲', '意甲', '德甲', '法甲', '欧联', '欧协联',
    '今天', '昨天', '最近', '最新', '新闻', '转会', '转会费', '伤', '伤病', '比分', '赛果',
    '比赛', '世界杯', '欧洲杯', '金球', '赛季', '排名', '积分',
    '签下', '签约', '官宣', '体检', '租借', '合同',
    '下课', '上任', '执教',
    '哈兰德', '姆巴佩', '萨拉赫', '凯恩', '贝林厄姆', '维尼修斯', '梅西', 'c罗',
    '赛程', '赛程表', '赛程安排', '赛程预告', '转会传闻', '最新消息',
    'today', 'yesterday', 'transfer', 'injury', 'signed', 'score', 'fixture', 'schedule',
]

def _should_search(query: str) -> bool:
    """判断是否需要联网搜索来获取实时信息。"""
    q = query.lower()
    return any(kw in q for kw in SEARCH_KEYWORDS)

# 赛程类问题：直接通过 football-data.org API 获取结构化数据，比搜索更准确
FIXTURE_KEYWORDS = ['赛程', '赛程表', '赛程安排', '赛程预告', 'fixture', 'schedule', '赛程查询']

def _needs_fixtures(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in FIXTURE_KEYWORDS)

async def search_web(query: str, max_results: int = 5) -> str:
    """使用 DuckDuckGo 搜索实时信息，返回纯文本摘要。"""
    if not HAS_WEB_SEARCH:
        return ""
    try:
        loop = asyncio.get_event_loop()
        def _execute():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        results = await asyncio.wait_for(
            loop.run_in_executor(None, _execute),
            timeout=10.0
        )
        if not results:
            return ""
        snippets = []
        for r in results:
            t = r.get('title', '').strip()
            b = r.get('body', '').strip()
            if t or b:
                line = f"• {t}：{b[:200]}" if t else f"• {b[:200]}"
                snippets.append(line)
        return "\n".join(snippets) if snippets else ""
    except Exception as e:
        print(f"[WebSearch Error] {e}")
        return ""

# --- 5. 外部数据拉取 ---
async def fetch_global_intel():
    now = time.time()
    if now - tactical_cache["last_update"] < 300 and tactical_cache["report"]:
        return tactical_cache["report"]

    headers = {"X-Auth-Token": FOOTBALL_API_TOKEN}
    summary_lines = []

    async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
        try:
            # 获取阿森纳比赛数据（包含已结束、进行中、已安排）
            res_ars = await client.get(
                f"https://api.football-data.org/v4/teams/{ARSENAL_ID}/matches?status=FINISHED,IN_PLAY,SCHEDULED",
                headers=headers
            )

            if res_ars.status_code == 200:
                ars_data = res_ars.json().get('matches', [])

                # 最近3场完赛
                finished = [m for m in ars_data if m['status'] == 'FINISHED']
                for m in finished[-3:]:
                    comp = m['competition']['name']
                    home = m['homeTeam']['shortName']
                    away = m['awayTeam']['shortName']
                    date = m['utcDate'][:10]
                    sh = m['score']['fullTime']['home']
                    sa = m['score']['fullTime']['away']
                    if sh is None:
                        sh = m['score'].get('regularTime', {}).get('home', 0)
                        sa = m['score'].get('regularTime', {}).get('away', 0)
                    summary_lines.append(f"🔴 阿森纳({date} {comp})：{home} {sh}:{sa} {away}")

                # 下一场赛程
                upcoming = [m for m in ars_data if m['status'] == 'SCHEDULED']
                if upcoming:
                    m = upcoming[0]
                    comp = m['competition']['name']
                    home = m['homeTeam']['shortName']
                    away = m['awayTeam']['shortName']
                    date = m['utcDate'][:10]
                    summary_lines.append(f"📅 下一场({date} {comp})：{home} vs {away}")

            # 获取英超积分榜（同原有逻辑）
            res_pl = await client.get("https://api.football-data.org/v4/competitions/PL/standings", headers=headers)
            if res_pl.status_code == 200:
                table = res_pl.json()['standings'][0]['table']
                key_teams = []
                for team in table:
                    pos = team['position']
                    name = team['team']['shortName']
                    pts = team['points']
                    tid = team['team']['id']

                    if pos == 1 or tid in (57, 64, 61, 65, 66) or pos >= 18:
                        key_teams.append(f"第{pos}名 {name} {pts}分")

                summary_lines.append(f"📊 英超关键排名：{' | '.join(key_teams)}")

            if not summary_lines:
                return "情报获取失败，无可用的实时数据。"

            final_report = "\n".join(summary_lines)
            tactical_cache["report"] = final_report
            tactical_cache["last_update"] = now
            return final_report

        except Exception as e:
            return f"数据链路离线 ({str(e)})。"

# 赛程专用缓存（10分钟）
fixture_cache = {"data": "", "last_update": 0}

async def fetch_pl_fixtures():
    """从 football-data.org 获取英超准确赛程。"""
    now = time.time()
    if now - fixture_cache["last_update"] < 600 and fixture_cache["data"]:
        return fixture_cache["data"]

    headers = {"X-Auth-Token": FOOTBALL_API_TOKEN}
    today = datetime.now().strftime('%Y-%m-%d')

    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            res = await client.get(
                f"https://api.football-data.org/v4/competitions/PL/matches?status=SCHEDULED&dateFrom={today}",
                headers=headers
            )
            if res.status_code != 200:
                return ""

            raw = res.json().get('matches', [])
            if not raw:
                return ""

            # 按轮次分组，取最近2轮
            groups = {}
            for m in raw:
                md = m.get('matchday', 0)
                groups.setdefault(md, [])
                home = m['homeTeam']['shortName']
                away = m['awayTeam']['shortName']
                date = m['utcDate'][:10]
                groups[md].append(f"  {date} {home} vs {away}")

            lines = []
            for md in sorted(groups.keys())[:2]:
                lines.append(f"第{md}轮：")
                lines.extend(groups[md])

            result = "\n".join(lines)
            fixture_cache["data"] = result
            fixture_cache["last_update"] = now
            return result
    except Exception as e:
        print(f"[Fixtures Error] {e}")
        return ""

# --- 5b. 图片识别（Vision API） ---
def _detect_image_format(data: bytes) -> str:
    """检测图片格式，返回 MIME 子类型（jpeg/png/gif/webp 等）"""
    if data.startswith(b'\xff\xd8'):
        return "jpeg"
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return "png"
    if data.startswith(b'GIF87a') or data.startswith(b'GIF89a'):
        return "gif"
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return "webp"
    if data.startswith(b'\x00\x00\x01\x00') or data.startswith(b'\x00\x00\x00\x1cftyp'):
        return "heic"
    return "jpeg"  # fallback

async def _download_image_to_file(url: str) -> Optional[str]:
    """下载图片到本地临时文件（参考备份项目 aiohttp + HTTP 降级方案）。返回文件路径。"""
    os.makedirs(TEMP_IMAGE_DIR, exist_ok=True)

    # 用 URL 哈希生成文件名，避免重复下载
    url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
    file_path = os.path.join(TEMP_IMAGE_DIR, f"{url_hash}.jpg")

    # 如果已存在且非空，直接返回
    if os.path.isfile(file_path) and os.path.getsize(file_path) > 0:
        return file_path

    http_url = url.replace("https://", "http://")

    # 策略1: aiohttp + HTTP（备份项目验证方案，无自定义 headers）
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(http_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 0:
                        with open(file_path, "wb") as f:
                            f.write(data)
                        return file_path
    except Exception:
        pass

    # 策略2: httpx + HTTPS（兜底）
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > 0:
                with open(file_path, "wb") as f:
                    f.write(resp.content)
                return file_path
    except Exception:
        pass

    return None

async def analyze_image(image_url: str) -> str:
    """下载图片到本地，调用 DeepSeek Vision API 返回图片内容描述。"""
    try:
        file_path = await _download_image_to_file(image_url)
        if file_path is None:
            return "[图片下载失败]"

        with open(file_path, "rb") as f:
            img_data = f.read()
        fmt = _detect_image_format(img_data)
        b64 = base64.b64encode(img_data).decode("utf-8")
        data_url = f"data:image/{fmt};base64,{b64}"
        return await analyze_image_base64(data_url)
    except Exception as e:
        return f"[图片识别异常：{type(e).__name__}: {e}]"

async def analyze_image_base64(data_url: str) -> str:
    """调用 Vision API 分析图片，主服务失败时自动 fallback 到备用服务。"""
    def _is_error(resp: str) -> bool:
        """判断 Vision API 返回值是否表示失败"""
        return resp.startswith("[图片识别失败") or resp.startswith("[图片识别异常")
    # 主服务：SiliconFlow Qwen3-VL-32B-Instruct
    result = await _call_vision_api(
        "https://api.siliconflow.cn", SILICONFLOW_API_KEY, SILICONFLOW_VISION_MODEL, data_url
    )
    if result and not _is_error(result):
        return result
    # 备用：duckcoding.ai gpt-4o-mini
    logger.warning(f"SiliconFlow 识别失败（{result}），fallback 到 duckcoding.ai")
    fallback = await _call_vision_api(IMAGE_API_URL, IMAGE_API_KEY, VISION_MODEL, data_url)
    if fallback and not _is_error(fallback):
        return fallback
    return f"[图片识别失败（SiliconFlow 和备用服务均失败）]"


async def _call_vision_api(api_url: str, api_key: str, model: str, data_url: str) -> str:
    """调用单个 Vision API 的底层函数。"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{api_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": "请用中文详细描述这张图片的内容，包括主要对象、场景、文字、表情等信息。"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ]}],
                    "max_tokens": 500,
                },
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
            try:
                body = resp.text[:200]
            except Exception:
                body = "(无法读取响应体)"
            return f"[图片识别失败：HTTP {resp.status_code} body={body}]"
    except Exception as e:
        return f"[图片识别异常：{type(e).__name__}: {e}]"

# --- 6. 数据库系统 ---
def init_db_safely():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # 原有 players 表
    c.execute('''CREATE TABLE IF NOT EXISTS players (user_id TEXT, group_id TEXT, nickname TEXT,
                 level TEXT DEFAULT '青训生', favorability INTEGER DEFAULT 0, last_seen INTEGER, PRIMARY KEY (user_id, group_id))''')
    # 新增：历史昵称表
    c.execute('''CREATE TABLE IF NOT EXISTS nicknames (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id TEXT NOT NULL,
                 group_id TEXT NOT NULL,
                 nickname TEXT NOT NULL,
                 first_seen INTEGER NOT NULL,
                 last_seen INTEGER NOT NULL,
                 UNIQUE(user_id, group_id, nickname))''')
    # 新增：发言记录表
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id TEXT NOT NULL,
                 group_id TEXT NOT NULL,
                 message TEXT NOT NULL,
                 timestamp INTEGER NOT NULL)''')
    # 迁移：添加 profile_json 列（存储人格画像 JSON）
    try:
        c.execute("ALTER TABLE players ADD COLUMN profile_json TEXT DEFAULT '{}'")
    except sqlite3.OperationalError:
        pass  # 列已存在
    # 新增：画像更新历史表
    c.execute('''CREATE TABLE IF NOT EXISTS profile_updates (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id TEXT NOT NULL,
                 group_id TEXT NOT NULL,
                 old_profile TEXT,
                 new_profile TEXT,
                 trigger_message TEXT,
                 timestamp INTEGER NOT NULL)''')
    # 成员互动关系表
    c.execute('''CREATE TABLE IF NOT EXISTS member_relations (
                 user_id TEXT NOT NULL,
                 target_user_id TEXT NOT NULL,
                 group_id TEXT NOT NULL,
                 interaction_count INTEGER DEFAULT 1,
                 last_interaction_time INTEGER NOT NULL,
                 PRIMARY KEY (user_id, target_user_id, group_id))''')
    conn.commit()
    conn.close()

init_db_safely()

# 注入工具模块配置
register_tools_config(
    football_api_token=FOOTBALL_API_TOKEN,
    deepseek_api_key=DEEPSEEK_API_KEY,
    arsenal_id=ARSENAL_ID,
    has_web_search=HAS_WEB_SEARCH,
)

# --- 7. 人格画像系统 ---
PROFILE_ANALYSIS_PROMPT = """你是一名记忆分析师，负责为足球俱乐部的每名成员建立详细的个人档案。
你需要根据该成员的发言记录，尽可能多地提取关于他/她的个人信息。你是一个记忆力超强的主教练，会记住每名球员的一切细节。

【当前档案】：
{current_profile}

【该成员最近 {count} 条发言记录】：
{recent_messages}

【当前昵称】：{nickname}
【身份等级】：{level}
【信任度】：{favorability}

请根据以上信息，输出更新后的完整档案 JSON。规则：
1. 保留原有信息中仍然准确的部分
2. 根据新发言修正或补充信息
3. 对于不确定的推测，标注"（推测）"
4. notable_events 尽量详细，保留所有值得记住的事情
5. 关注以下维度（尽可能从发言中挖掘）：
   - real_name: 真实姓名（如果提到过）
   - nicknames: 所有已知的外号、别名、绰号（列表形式，如 ["小胖", "鸽子"]）
   - personality: 性格特征（开朗/内向/暴躁/幽默/严肃/话痨/沉默等）
   - interests: 兴趣爱好（不限于足球，游戏、音乐、电影、运动等）
   - favorite_team: 支持的球队（从发言中推断）
   - rival_teams: 讨厌的球队
   - speaking_style: 说话风格（正式/随意/粗鲁/礼貌/爱用表情/方言/口头禅等）
   - background: 背景信息（学生/打工人/年龄/学校/职业/所在地等）
   - relationship_with_arteta: 与阿尔特塔的关系描述
   - notable_events: 值得记住的关键事件（越多越好，包括他说过的有趣的话、做过的事、暴露的秘密等）

重点提取方向：
- 如果他提到了自己的名字、外号、年龄、学校、工作，一定要记录
- 如果他有独特的口头禅或说话习惯，记录下来
- 如果他暴露了什么糗事或秘密，记在 notable_events 里
- 如果他和其他群成员有特殊关系，也可以记录

只输出 JSON，不要有任何其他文字。
格式：
{{
  "real_name": "...",
  "nicknames": ["...", "..."],
  "personality": "...",
  "interests": "...",
  "favorite_team": "...",
  "rival_teams": "...",
  "speaking_style": "...",
  "background": "...",
  "relationship_with_arteta": "...",
  "notable_events": "...",
  "last_profile_update": {now},
  "message_count_at_update": {total_count}
}}
"""

async def get_message_count(user_id: str, group_id: str) -> int:
    """获取用户消息总数"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM messages WHERE user_id = ? AND group_id = ?",
            (user_id, group_id)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def track_member_interaction(user_id: str, target_id: str, group_id: str):
    """记录用户 A 与用户 B 之间的互动（回复/@），建立关系数据"""
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""INSERT INTO member_relations (user_id, target_user_id, group_id, interaction_count, last_interaction_time)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(user_id, target_user_id, group_id)
            DO UPDATE SET interaction_count = interaction_count + 1, last_interaction_time = ?""",
            (user_id, target_id, group_id, now, now))
        await db.commit()


def get_active_members_snapshot(group_id: str, limit: int = 8) -> str:
    """返回近 24h 活跃成员摘要字符串，用于注入 prompt"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cutoff = int(time.time()) - 86400
        rows = conn.execute("""
            SELECT p.user_id, p.nickname, p.level, p.favorability,
                   COUNT(m.id) as msg_count
            FROM players p
            LEFT JOIN messages m ON p.user_id = m.user_id AND p.group_id = m.group_id AND m.timestamp > ?
            WHERE p.group_id = ?
            GROUP BY p.user_id
            HAVING msg_count > 0
            ORDER BY msg_count DESC
            LIMIT ?
        """, (cutoff, group_id, limit)).fetchall()
        conn.close()

        if not rows:
            return "暂无活跃球员数据。"

        parts = []
        for uid, nick, lvl, fav, count in rows:
            level_icon = {"传奇队长": "★", "核心首发": "◆", "一线队": "●", "青训生": "○", "预备队": "△", "看台内鬼": "▼"}
            icon = level_icon.get(lvl, "○")
            parts.append(f"{nick}{icon}(好感{fav})")
        return "、".join(parts)
    except Exception:
        return "暂无活跃球员数据。"


async def should_update_profile(user_id: str, group_id: str, message_count: int) -> bool:
    """判断是否需要触发画像更新"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT profile_json FROM players WHERE user_id = ? AND group_id = ?",
            (user_id, group_id)
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        return False

    profile = json.loads(row[0]) if row[0] and row[0] != '{}' else {}
    now = int(time.time())

    last_update = profile.get("last_profile_update", 0)
    count_at_update = profile.get("message_count_at_update", 0)
    messages_since = message_count - count_at_update

    # 冷却期：10 分钟内不重复更新
    if now - last_update < 600:
        return False

    # 新用户：3 条消息后触发初始化
    if not profile.get("personality") and message_count >= 3:
        return True

    # 时间阈值：超过 24 小时触发
    if now - last_update > 86400:
        return True

    # 消息数量阈值：每 5 条消息触发
    if messages_since >= 5:
        return True

    return False

async def update_user_profile(user_id: str, group_id: str, nickname: str, level: str, favorability: int):
    """调用 LLM 分析用户消息并更新人格画像"""
    now = int(time.time())
    print(f"[Profile] 开始更新 {nickname}({user_id}) 的画像...")

    # 获取当前画像
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT profile_json FROM players WHERE user_id = ? AND group_id = ?",
            (user_id, group_id)
        ) as cursor:
            row = await cursor.fetchone()

    current_profile = row[0] if row and row[0] else '{}'

    # 获取消息总数
    total_count = await get_message_count(user_id, group_id)
    print(f"[Profile] {nickname} 消息总数: {total_count}")

    # 获取最近 20 条消息用于分析
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT message, timestamp FROM messages WHERE user_id = ? AND group_id = ? ORDER BY timestamp DESC LIMIT 20",
            (user_id, group_id)
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        print(f"[Profile] {nickname} 没有消息记录，跳过更新")
        return

    recent_messages = "\n".join(
        f"[{datetime.fromtimestamp(r[1]).strftime('%m-%d %H:%M')}] {r[0]}"
        for r in reversed(rows)
    )

    # 构建分析 prompt
    prompt = PROFILE_ANALYSIS_PROMPT.format(
        current_profile=current_profile,
        count=len(rows),
        recent_messages=recent_messages,
        nickname=nickname,
        level=level,
        favorability=favorability,
        now=now,
        total_count=total_count
    )

    # 调用 LLM 进行画像分析
    try:
        print(f"[Profile] 正在调用 LLM 分析 {nickname} 的画像...")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3
                }
            )

            print(f"[Profile] LLM 响应状态码: {resp.status_code}")
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"].strip()
                print(f"[Profile] LLM 原始响应前200字: {raw[:200]}")
                # 提取 JSON（处理 markdown 代码块）
                json_match = re.search(r'\{[\s\S]*\}', raw)
                if json_match:
                    new_profile = json_match.group(0)
                    # 验证 JSON 格式
                    json.loads(new_profile)
                    print(f"[Profile] 解析到的画像 JSON: {new_profile[:200]}")

                    # 保存到数据库
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "UPDATE players SET profile_json = ? WHERE user_id = ? AND group_id = ?",
                            (new_profile, user_id, group_id)
                        )
                        # 记录更新历史
                        await db.execute(
                            "INSERT INTO profile_updates (user_id, group_id, old_profile, new_profile, trigger_message, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                            (user_id, group_id, current_profile, new_profile, recent_messages.split('\n')[-1] if recent_messages else "", now)
                        )
                        await db.commit()

                    print(f"[Profile] ✅ 已成功更新 {nickname}({user_id}) 的人格画像")
                else:
                    print(f"[Profile] ❌ 无法从 LLM 响应中提取 JSON")
            else:
                print(f"[Profile] ❌ LLM 调用失败，状态码: {resp.status_code}")
                print(f"[Profile] 响应内容: {resp.text[:500]}")
    except Exception as e:
        print(f"[Profile] ❌ 更新画像失败 {user_id}: {type(e).__name__}: {e}")

async def get_profile_section(user_id: str, group_id: str) -> str:
    """获取用户画像的 prompt 片段"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT profile_json FROM players WHERE user_id = ? AND group_id = ?",
            (user_id, group_id)
        ) as cursor:
            row = await cursor.fetchone()

    if not row or not row[0] or row[0] == '{}':
        return ""

    profile = json.loads(row[0])

    if not profile.get("personality"):
        return ""

    # 处理外号列表
    nicknames = profile.get('nicknames', [])
    nicknames_str = "、".join(nicknames) if nicknames else "暂无"

    return f"""
【球员个人档案——你对这名球员的了解】：
真实姓名：{profile.get('real_name', '暂无')}
外号/别名：{nicknames_str}
性格特征：{profile.get('personality', '暂无')}
兴趣爱好：{profile.get('interests', '暂无')}
支持球队：{profile.get('favorite_team', '暂无')}
讨厌球队：{profile.get('rival_teams', '暂无')}
说话风格：{profile.get('speaking_style', '暂无')}
背景信息：{profile.get('background', '暂无')}
你们的关系：{profile.get('relationship_with_arteta', '暂无')}
值得记住的事：{profile.get('notable_events', '暂无')}
"""

async def update_nickname_history(user_id: str, group_id: str, nickname: str):
    """更新昵称历史记录"""
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        # 检查是否已存在该昵称记录
        async with db.execute(
            "SELECT id, last_seen FROM nicknames WHERE user_id = ? AND group_id = ? AND nickname = ?",
            (user_id, group_id, nickname)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                # 更新 last_seen
                await db.execute(
                    "UPDATE nicknames SET last_seen = ? WHERE id = ?",
                    (now, row[0])
                )
            else:
                # 插入新昵称记录
                await db.execute(
                    "INSERT INTO nicknames (user_id, group_id, nickname, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
                    (user_id, group_id, nickname, now, now)
                )
        await db.commit()

async def save_message(user_id: str, group_id: str, message: str):
    """保存发言记录"""
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (user_id, group_id, message, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, group_id, message, now)
        )
        await db.commit()

async def get_user_profile(user_id: str, group_id: str) -> dict:
    """获取用户完整档案"""
    profile = {
        "user_id": user_id,
        "current_nickname": "",
        "level": "",
        "favorability": 0,
        "last_seen": 0,
        "nicknames": [],
        "recent_messages": [],
        "message_count": 0,
        "personality_profile": {}
    }

    async with aiosqlite.connect(DB_PATH) as db:
        # 获取当前玩家信息（包括 profile_json）
        async with db.execute(
            "SELECT nickname, level, favorability, last_seen, profile_json FROM players WHERE user_id = ? AND group_id = ?",
            (user_id, group_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                profile["current_nickname"] = row[0]
                profile["level"] = row[1]
                profile["favorability"] = row[2]
                profile["last_seen"] = row[3]
                if row[4] and row[4] != '{}':
                    try:
                        profile["personality_profile"] = json.loads(row[4])
                    except json.JSONDecodeError:
                        profile["personality_profile"] = {}

        # 获取历史昵称（最近10个）
        async with db.execute(
            "SELECT nickname, first_seen, last_seen FROM nicknames WHERE user_id = ? AND group_id = ? ORDER BY last_seen DESC LIMIT 10",
            (user_id, group_id)
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                profile["nicknames"].append({
                    "nickname": row[0],
                    "first_seen": row[1],
                    "last_seen": row[2]
                })

        # 获取发言总数
        async with db.execute(
            "SELECT COUNT(*) FROM messages WHERE user_id = ? AND group_id = ?",
            (user_id, group_id)
        ) as cursor:
            row = await cursor.fetchone()
            profile["message_count"] = row[0] if row else 0

        # 获取最近发言（最近20条）
        async with db.execute(
            "SELECT message, timestamp FROM messages WHERE user_id = ? AND group_id = ? ORDER BY timestamp DESC LIMIT 20",
            (user_id, group_id)
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                profile["recent_messages"].append({
                    "message": row[0],
                    "timestamp": row[1]
                })

    return profile

# --- 好感度关键词辅助检测（在 LLM 评估基础上额外扣分） ---
FAVOR_HEAVY_NEGATIVE = [
    "狗屎", "傻逼", "沙比", "傻比", "草泥马", "cnm", "尼玛死了", "你妈死了",
    "操你妈", "去死", "吃屎", "你妈", "他妈", "tm的", "操你", "艹你",
    "操", "艹", "妈的", "你妈的", "他妈的", "草", "我草",
    "畜生", "狗东西", "狗娘养的", "杂种", "婊子", "傻狗", "狗比",
    "脑瘫", "智障", "nmsl", "死妈", "全家死", "司马", "死全家",
    "你妈炸了", "神经病",
    "垃圾球队", "解散吧", "废物教练", "垃圾教练", "阿森纳解散", "什么垃圾", "垃圾东西",
    "什么玩意儿", "什么垃圾玩意儿", "垃圾玩意儿", "死垃圾", "废物东西",
    "阿尔特塔滚", "arteta滚", "阿森纳滚", "arteta下课", "滚出阿森纳",
    "塔牲", "塔嗨", "董卓", "阿森纳垃圾",
    "傻逼东西", "狗屎玩意", "去死吧", "你怎么不去死",
]
FAVOR_MODERATE_NEGATIVE = [
    "下课", "解雇", "退役", "滚球", "滚蛋", "滚吧",
    "废物", "垃圾", "真垃圾", "太垃圾", "菜鸡", "真菜", "太菜",
    "业余", "就这水平", "就这", "就这啊", "菜狗", "菜鸟",
    "脑残", "煞笔", "sb", "s b", "傻", "蠢", "笨",
    "傻x", "傻叉", "白痴", "弱智", "低能", "蠢货", "二百五",
    "有毒", "倒闭", "有病", "有病吧", "恶心", "差劲",
    "烦死了", "受不了", "什么玩意", "啥啊", "什么鬼", "真没救",
    "没救", "没救了",
    "滚", "你行你上", "懂王", "装逼", "装什么",
    "娜娜",
]
FAVOR_LIGHT_NEGATIVE = [
    "菜", "不行", "无语", "哎", "算了", "失望", "摆烂",
    "服了", "麻了", "醉了", "太差", "不行啊",
    "无聊", "没意思", "什么啊", "搞什么", "烦",
    "干啥", "真的菜", "有点菜", "不太行", "好菜", "真不行",
    "无奈", "拉胯", "抽象", "下饭", "难绷",
]


def check_keyword_penalty(prompt: str) -> (int, str):
    """检测发言中的负面关键词，返回额外扣分和原因"""
    p = prompt.lower()
    for kw in FAVOR_HEAVY_NEGATIVE:
        if kw in p:
            return random.randint(-80, -40), f"（触发敏感词：{kw}）"
    for kw in FAVOR_MODERATE_NEGATIVE:
        if kw in p:
            return random.randint(-40, -15), f"（触发敏感词：{kw}）"
    for kw in FAVOR_LIGHT_NEGATIVE:
        if kw in p:
            return random.randint(-20, -5), f"（触发敏感词：{kw}）"
    return 0, ""


# --- 好感度标记系统（LLM 评估，比关键词更智能） ---
FAVOR_MARKERS = {
    "【好感度+++】": (380, 770, "令人惊叹的表现，极大提升了信任度"),
    "【好感度++】": (200, 370, "出色的交流，大幅提升了信任度"),
    "【好感度+】": (10, 190, "积极的互动，提升了信任度"),
    "【好感度=】": (0, 0, ""),
    "【好感度-】": (-190, -10, "不当言行，降低了信任度"),
    "【好感度--】": (-370, -200, "严重的负面言行，大幅降低了信任度"),
    "【好感度---】": (-770, -380, "极端恶劣的言行，信任度严重受损"),
}

def extract_favor_marker(text: str) -> Optional[str]:
    """从 LLM 回复中提取好感度标记（取最后一个出现的）"""
    found = []
    for marker in FAVOR_MARKERS:
        for m in re.finditer(re.escape(marker), text):
            found.append((m.start(), marker))
    if not found:
        return None
    found.sort(key=lambda x: x[0])
    return found[-1][1]

FAVOR_LEVEL_THRESHOLDS = [
    ("看台内鬼", -50),
    ("预备队", 0),
    ("青训生", 50),
    ("一线队", 200),
    ("核心首发", 500),
    ("传奇队长", float("inf")),
]

async def get_player_data(user_id: str, group_id: str, nickname: str):
    """获取球员当前数据并更新昵称历史"""
    await update_nickname_history(user_id, group_id, nickname)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT level, favorability FROM players WHERE user_id = ? AND group_id = ?",
                              (user_id, group_id)) as cursor:
            row = await cursor.fetchone()
    return (row[0], row[1]) if row else ("青训生", 0)


async def apply_favor_change(user_id: str, group_id: str, nickname: str, inc: int, is_admin: bool = False):
    """应用好感度变更并返回更新后的 (level, favorability)"""
    if is_admin:
        # 管理员固定满值
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''INSERT INTO players (user_id, group_id, nickname, favorability, level, last_seen)
                                VALUES (?, ?, ?, ?, ?, ?)
                                ON CONFLICT(user_id, group_id) DO UPDATE SET
                                favorability = 999999, level = '传奇队长', nickname = excluded.nickname, last_seen = excluded.last_seen''',
                             (user_id, group_id, nickname, 999999, "传奇队长", int(time.time())))
            await db.commit()
        return ("传奇队长", 999999)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''INSERT INTO players (user_id, group_id, nickname, favorability, last_seen)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(user_id, group_id) DO UPDATE SET
                            favorability = favorability + ?, nickname = excluded.nickname, last_seen = excluded.last_seen''',
                         (user_id, group_id, nickname, max(0, inc), int(time.time()), inc))
        async with db.execute("SELECT favorability FROM players WHERE user_id = ? AND group_id = ?",
                              (user_id, group_id)) as cursor:
            row = await cursor.fetchone()
        current_fav = row[0] if row else 0
        new_level = "看台内鬼"
        for lvl, threshold in FAVOR_LEVEL_THRESHOLDS:
            if current_fav < threshold:
                new_level = lvl
                break
        await db.execute("UPDATE players SET level = ? WHERE user_id = ? AND group_id = ?",
                         (new_level, user_id, group_id))
        await db.commit()
        return new_level, current_fav


# --- 递归引用消息链提取 ---
async def fetch_quoted_chain(bot: Bot, message_id: int) -> str:
    """递归提取引用消息链，最多 3 层。返回由旧到新的缩进格式文本。"""

    async def _collect(mid: int, depth: int, chain: list):
        """收集引用链条目到 chain 列表（新→旧），异常时占位。"""
        try:
            msg_data = await asyncio.wait_for(bot.get_msg(message_id=mid), timeout=45.0)
            with open("/tmp/debug.log", "a") as df:
                df.write(f"_collect mid={mid} depth={depth}\n")
                df.write(f"  msg_data keys={list(msg_data.keys())}\n")
                if isinstance(msg_data.get("message"), list):
                    seg_types = [s.get("type") for s in msg_data["message"]]
                    df.write(f"  segment types={seg_types}\n")
                    for s in msg_data["message"]:
                        if s.get("type") == "forward":
                            df.write(f"  forward seg data={json.dumps(s.get('data',{}), ensure_ascii=False)}\n")
            sender = msg_data.get("sender", {})
            sender_name = sender.get("card") or sender.get("nickname") or "未知"
            sender_qq = str(sender.get("user_id", ""))

            raw_msg = msg_data.get("message", [])

            # 检测是否为合并转发（forward）类型
            forward_id = None
            if isinstance(raw_msg, list):
                for seg in raw_msg:
                    if seg.get("type") == "forward":
                        forward_id = seg.get("data", {}).get("id")
                        break

            if forward_id:
                # 展开合并转发：获取内部消息列表
                chain.append((sender_name, sender_qq, "[合并转发]", False))
                try:
                    with open("/tmp/debug.log", "a") as df:
                        df.write(f"  forward_id={forward_id}\n")
                    # NapCat 在 bot.get_msg() 的 forward segment 中已内联了 data.content
                    # 直接从已获取的数据中提取，无需额外 API 调用
                    content_msgs = []
                    if isinstance(raw_msg, list):
                        for seg in raw_msg:
                            if seg.get("type") == "forward":
                                content = seg.get("data", {}).get("content")
                                if isinstance(content, list):
                                    content_msgs = content
                                break
                    with open("/tmp/debug.log", "a") as df:
                        df.write(f"  content_msgs count={len(content_msgs)}\n")
                    for f_msg in content_msgs[:15]:  # 最多展示 15 条
                        f_sender = f_msg.get("sender", {})
                        f_name = f_sender.get("card") or f_sender.get("nickname") or "未知"
                        f_qq = str(f_sender.get("user_id", ""))
                        f_raw = f_msg.get("message", [])
                        if isinstance(f_raw, list):
                            f_text = "".join(
                                s.get("data", {}).get("text", "")
                                for s in f_raw if s.get("type") == "text"
                            ).strip()
                        else:
                            f_text = str(f_raw).strip()
                        if not f_text:
                            f_text = "[非文本消息]"
                        chain.append((f_name, f_qq, f_text, True))
                    if not content_msgs:
                        # 没有内联内容，标记获取失败
                        chain.append(("", "", "[转发内容为空或无法解析]", True))
                except Exception as e:
                    chain.append(("", "", f"[转发内容解析失败：{e}]", True))
            else:
                # 普通消息：提取文本和图片
                if isinstance(raw_msg, list):
                    text_parts = [
                        s.get("data", {}).get("text", "")
                        for s in raw_msg if s.get("type") == "text"
                    ]
                    text_content = "".join(text_parts).strip()

                    # 提取并识别图片内容（简化逻辑，不从本地路径读取）
                    img_descriptions = []
                    for s in raw_msg:
                        if s.get("type") == "image":
                            file_id = s.get("data", {}).get("file")
                            with open("/tmp/debug.log", "a") as df:
                                df.write(f"  Image found, file_id={file_id}\n")
                            try:
                                # 优先从 bot.get_image() 获取最新 URL（含最新 auth 参数）
                                img_url = None
                                if file_id:
                                    img_info = await asyncio.wait_for(bot.get_image(file=file_id), timeout=45.0)
                                    img_url = img_info.get("url")
                                    with open("/tmp/debug.log", "a") as df:
                                        df.write(f"  get_image returned url={img_url}\n")
                                # fallback: 直接从消息数据取 URL
                                if not img_url:
                                    img_url = s.get("data", {}).get("url")
                                if img_url:
                                    desc = await analyze_image(img_url)
                                    img_descriptions.append(desc)
                                else:
                                    img_descriptions.append("[图片获取失败]")
                            except Exception as e:
                                with open("/tmp/debug.log", "a") as df:
                                    df.write(f"  Image processing exception: {type(e).__name__}: {e}\n")
                                img_descriptions.append(f"[图片识别异常：{e}]")
                    if img_descriptions:
                        img_text = "；".join(img_descriptions)
                        text_content = (text_content + " [图片内容：" + img_text + "]").strip()
                else:
                    text_content = str(raw_msg).strip()
                if not text_content:
                    text_content = "[仅含非文本内容]"
                chain.append((sender_name, sender_qq, text_content, False))

            # 检测嵌套引用
            for seg in raw_msg if isinstance(raw_msg, list) else []:
                if seg.get("type") == "reply" and depth < 2:
                    nested_id = seg.get("data", {}).get("id")
                    if nested_id:
                        await _collect(int(nested_id), depth + 1, chain)
                    break
        except Exception as e:
            chain.append((f"[消息获取失败：{e}]", "", "", False))

    chain = []
    await _collect(message_id, 0, chain)
    # chain = [最新, ..., 最旧] → 反转得到 [最旧, ..., 最新]
    chain.reverse()

    lines = []
    entry_idx = 0  # 只对非转发子条目计数，用于缩进层级
    for name, qq, text, is_child in chain:
        if is_child:
            # 合并转发子条目：额外缩进 + └ 前缀
            qq_suffix = f"({qq})" if qq else ""
            lines.append(f"    └ {name}{qq_suffix}：{text}")
        else:
            indent = "  " * entry_idx
            prefix = "原始消息" if entry_idx == 0 else "↳"
            sep = " - " if entry_idx == 0 else " "
            qq_suffix = f"({qq})" if qq else ""
            lines.append(f"{indent}{prefix}{sep}{name}{qq_suffix}：{text}")
            entry_idx += 1

    return "\n".join(lines)


# --- 7. 核心引擎与路由 ---
async def process_chat(bot: Bot, event: MessageEvent, custom_prompt: str = None):
    import json
    with open("/tmp/debug.log", "a") as df:
        df.write(f"process_chat called, custom_prompt={custom_prompt}\n")
        msg = event.get_message()
        df.write(f"msg type={type(msg).__name__}\n")
        segs = list(msg)
        df.write(f"segments count={len(segs)}\n")
        for i, seg in enumerate(segs):
            df.write(f"  seg[{i}] type={seg.type} data={json.dumps(dict(seg.data), ensure_ascii=False)}\n")
        df.write(f"plain_text={msg.extract_plain_text()[:100]!r}\n")
        # Check event.reply (NoneBot OneBot V11 reply attribute)
        reply = getattr(event, 'reply', None)
        df.write(f"event.reply={reply}\n")
        if reply:
            df.write(f"reply.message_id={getattr(reply, 'message_id', None)}\n")
            df.write(f"reply.sender={getattr(reply, 'sender', None)}\n")
        # Check original message
        orig = getattr(event, 'original_message', None)
        df.write(f"original_message={orig}\n")
        orig_segs = list(orig) if orig else []
        for i, s in enumerate(orig_segs):
            df.write(f"  orig[{i}] type={s.type} data={json.dumps(dict(s.data), ensure_ascii=False)}\n")

    user_id, group_id = event.get_user_id(), str(event.group_id) if isinstance(event, GroupMessageEvent) else "private"
    nickname = event.sender.card or event.sender.nickname or "未知球员"

    # 保存发言记录（仅非自定义 prompt 时）
    if not custom_prompt:
        raw_message = event.get_message().extract_plain_text().strip()
        if raw_message:
            await save_message(user_id, group_id, raw_message)

    prompt = custom_prompt if custom_prompt else event.get_message().extract_plain_text().strip()
    if not custom_prompt and prompt.lower().startswith("a"):
        prompt = prompt[1:].strip()

    # 检测引用回复链：递归提取最多 3 层引用消息
    quoted_text = ""
    reply_id = None
    chain_text = ""

    # 方式1：从消息段中找 reply 类型
    for seg in event.get_message():
        if seg.type == "reply":
            reply_id = seg.data.get("id")
            with open("/tmp/debug.log", "a") as df:
                df.write(f"reply seg found via seg.type, reply_id={reply_id}\n")
            break

    # 方式2：从 event.reply 获取（NapCat/部分OneBot实现）
    if not reply_id:
        reply = getattr(event, 'reply', None)
        if reply:
            reply_id = getattr(reply, 'message_id', None)
            with open("/tmp/debug.log", "a") as df:
                df.write(f"reply found via event.reply, reply_id={reply_id}\n")

    if reply_id:
        chain_text = await fetch_quoted_chain(bot, int(reply_id))
        with open("/tmp/debug.log", "a") as df:
            df.write(f"chain_text length={len(chain_text) if chain_text else 0}\n")
            if chain_text:
                df.write(f"chain_text content={chain_text[:500]}\n")
        if chain_text:
            quoted_text = "\n\n【引用消息链（由旧到新）】：\n" + chain_text

    # --- 互动追踪：记录成员间的回复/@ 关系 ---
    if not custom_prompt:
        # 追踪回复关系：当前用户 → 被回复的用户
        reply_to_id = None
        reply_event = getattr(event, 'reply', None)
        if reply_event:
            reply_to_id = str(getattr(reply_event, 'user_id', '')) or str(getattr(getattr(reply_event, 'sender', None), 'user_id', ''))
        if not reply_to_id and chain_text:
            # 从引用链第一行提取被回复人的 QQ
            import re as _re
            m = _re.search(r'\((\d+)\)', chain_text.split('\n')[0] if chain_text else '')
            if m:
                reply_to_id = m.group(1)
        if reply_to_id and reply_to_id != user_id and reply_to_id != bot.self_id:
            await track_member_interaction(user_id, reply_to_id, group_id)

        # 追踪 @ 关系
        for seg in event.get_message():
            if seg.type == "at":
                target_id = str(seg.data.get("qq", ""))
                if target_id and target_id != user_id and target_id != bot.self_id:
                    await track_member_interaction(user_id, target_id, group_id)

    # 分析当前消息中的图片
    img_analysis = ""
    if not custom_prompt:
        img_urls = [s.data.get("url") for s in event.get_message() if s.type == "image" and s.data.get("url")]
        if img_urls:
            descs = await asyncio.gather(*[analyze_image(u) for u in img_urls])
            img_analysis = "\n\n【用户发送的图片内容】：" + "；".join(descs)

    # --- 联网搜索：对涉及现实足球/实时信息的问题抓取最新情报，避免幻觉 ---
    search_results = ""
    if _should_search(prompt):
        search_results = await search_web(prompt)

    # --- 赛程查询：对赛程类问题直接通过 API 获取结构化数据，比联网搜索更准确 ---
    fixture_data = ""
    if _needs_fixtures(prompt):
        fixture_data = await fetch_pl_fixtures()

    # --- 用 LLM 评估好感度（在 LLM 回复后处理），之前只获取当前数据 ---
    lvl, fav = await get_player_data(user_id, group_id, nickname)

    # 获取消息数量并检查是否需要更新画像
    msg_count = await get_message_count(user_id, group_id)

    # 加载用户画像
    profile_section = await get_profile_section(user_id, group_id)

    # 获取系统当前的准确时间，作为大模型的"现实时间基准"
    current_time = datetime.now().strftime('%Y年%m月%d日 %H:%M')

    # --- 群活跃成员快照：让阿尔特塔知道更衣室里有谁 ---
    group_snapshot = get_active_members_snapshot(group_id)

    # --- 当前一线队阵容：直接注入让 LLM 不依赖训练数据中的旧名单 ---
    current_squad = ""
    try:
        squad_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge_base", "arsenal_knowledge_base.md")
        if os.path.exists(squad_path):
            with open(squad_path, "r", encoding="utf-8") as f:
                squad_content = f.read()
            # 只取球员名单部分
            start = squad_content.find("### 守门员")
            end = squad_content.find("\n## ", start) if start > 0 else len(squad_content)
            if start > 0:
                current_squad = "\n【当前一线队阵容（阿森纳2025-26赛季）】：\n" + squad_content[start:end].strip()
    except Exception:
        pass

    # --- Function Calling 版本：简化 Base Prompt，数据由 LLM 按需通过 tool use 获取 ---
    base_prompt = (
        f"{ARTETA_PROMPT}\n\n"
        f"【背景信息】：\n当前时间：{current_time}\n群号：{group_id}\n{quoted_text}{img_analysis}\n"
        f"当前提问球员：{nickname}，身份：{lvl}，当前信任度：{fav}。\n"
        f"{current_squad}\n"
        f"{profile_section}\n"
        f"【更衣室概况】：{group_snapshot}\n"
        f"（你可以使用 get_group_members 查看完整活跃球员名单，"
        f"使用 get_member_relations 了解球员之间的关系。\n"
        f"【个性化回复要求】：根据你对该球员的了解，调整你的回复风格和态度。"
        f"如果他是热刺球迷，可以适当调侃；如果他是忠实枪迷，给予更多鼓励；"
        f"如果他说话风格粗鲁，你可以严厉一些；如果他礼貌认真，你也可以更温和。"
        f"表现出你记得和这名球员之间的过往互动。"
    )
    
    # 构建用户消息
    user_message = prompt
    if quoted_text:
        user_message = f"{prompt}\n\n【引用的消息】：{quoted_text.replace('【引用消息链（由旧到新）】：', '').strip()}"

    messages = [{"role": "system", "content": base_prompt}]

    # 从 ChromaDB 检索本群相关历史记忆
    memory_contexts = memory_store.query_memories(group_id, user_message)
    if memory_contexts:
        memory_block = "\n\n".join(memory_contexts)
        memory_banner = f"\n\n【相关历史对话（本群）】：\n{memory_block}\n"
        messages[0]["content"] += memory_banner

    messages.append({"role": "user", "content": user_message})

    # 立即发送提示消息（不阻塞心跳）
    await bot.send(event, Message("\U0001f4cb 教练在战术板上写分析，马上就好..."))

    async def delayed_response():
        try:
            answer = await asyncio.wait_for(run_tool_loop(messages), timeout=30.0)
        except asyncio.TimeoutError:
            await bot.send(event, Message("⏰ 教练这次思考太久，重新说一遍？"))
            return
        except Exception as e:
            await bot.send(event, Message(f"连接中断：{str(e)}"))
            return

        if answer:
            try:
                with open("/tmp/debug.log", "a") as df:
                    df.write(f"FC answer (first 500): {answer[:500]}\n")

                # --- LLM 好感度评估：从回复中提取标记 ---
                inc, reason = 0, ""
                marker = extract_favor_marker(answer)
                is_admin = (user_id == ADMIN_QQ)
                if marker and marker in FAVOR_MARKERS:
                    min_val, max_val, marker_reason = FAVOR_MARKERS[marker]
                    if min_val != 0:
                        inc = random.randint(min(min_val, max_val), max(min_val, max_val))
                    reason = marker_reason

                    # 从显示文本中移除标记
                    answer = re.sub(r'\s*' + re.escape(marker) + r'\s*$', '', answer).rstrip()
                else:
                    with open("/tmp/debug.log", "a") as df:
                        df.write(f"[FAV] user={user_id} no marker found\n")

                # --- 关键词辅助检测：在 LLM 评估基础上额外扣分 ---
                kw_penalty, kw_reason = check_keyword_penalty(prompt) if not is_admin else (0, "")
                if kw_penalty < 0:
                    inc += kw_penalty
                    reason = (reason + kw_reason) if reason else kw_reason.lstrip("（").rstrip("）")
                    with open("/tmp/debug.log", "a") as df:
                        df.write(f"[FAV] keyword extra: {kw_penalty} reason={kw_reason}\n")

                # 应用好感度变更（管理员不参与）
                if not is_admin:
                    lvl, fav = await apply_favor_change(user_id, group_id, nickname, inc)
                else:
                    lvl, fav = await apply_favor_change(user_id, group_id, nickname, 0, is_admin=True)

                with open("/tmp/debug.log", "a") as df:
                    df.write(f"[FAV] user={user_id} nick={nickname} inc={inc} reason={reason}\n")

                # 检查是否需要更新画像
                if await should_update_profile(user_id, group_id, msg_count):
                    asyncio.create_task(update_user_profile(user_id, group_id, nickname, lvl, fav))

                memory_store.add_memory(group_id, user_id, user_message, answer)

                # 好感度变动红字（由代码保证总是显示）
                if inc > 0:
                    answer += f"\n\n[red]【信任度上升{abs(inc)}点 - {reason}】[/red]"
                elif inc < 0:
                    answer += f"\n\n[red]【信任度下降{abs(inc)}点 - {reason}】[/red]"
                else:
                    answer += f"\n\n[red]【信任度无变化】[/red]"

                if needs_html_render(answer):
                    with open("/tmp/debug.log", "a") as df:
                        df.write(f"RENDER: needs_html_render=True, trying html_to_image\n")
                    html_answer = answer.replace("[red]", '<span class="arsenal-red">')
                    html_answer = html_answer.replace("[/red]", '</span>')
                    html_answer = html_answer.replace("[blue]", '<span class="arsenal-blue">')
                    html_answer = html_answer.replace("[/blue]", '</span>')
                    try:
                        img_bytes = await html_to_image(html_answer)
                    except Exception as e:
                        with open("/tmp/debug.log", "a") as df:
                            df.write(f"RENDER: html_to_image failed: {e}, falling back to PIL\n")
                        img_bytes = text_to_tactical_board(answer)
                else:
                    img_bytes = text_to_tactical_board(answer)
                await bot.send(event, MessageSegment.image(img_bytes))
            except Exception as e:
                await bot.send(event, Message(f"回复处理出错：{str(e)}"))
        else:
            await bot.send(event, Message("让我想想再回答你。"))

    asyncio.create_task(delayed_response())

@notice_handler.handle()
async def handle_notices(bot: Bot, event: NoticeEvent):
    raw = event.dict()
    sid, tid, gid, sub = str(raw.get("user_id", "")), str(raw.get("target_id", "")), str(raw.get("group_id", "")), raw.get("sub_type", "")
    if sub in ["poke", "pat"]:
        if sid == ADMIN_QQ and tid != str(bot.self_id):
            await bot.send_group_msg(group_id=int(gid), message="（满意地点头）这名球员展现了惊人的能量，我们在关注他。")
            await bot.call_api("group_poke", group_id=int(gid), user_id=int(tid))
        elif tid == str(bot.self_id):
            await bot.send_group_msg(group_id=int(gid), message="保持你的专注度！在场上你需要自主做出正确的决策！")
            await bot.call_api("group_poke", group_id=int(gid), user_id=int(sid))

@refresh_cmd.handle()
async def handle_refresh(bot: Bot, event: MessageEvent):
    global tactical_cache
    tactical_cache["last_update"] = 0
    tactical_cache["report"] = ""
    
    intel = await fetch_global_intel()
    reply = (
        f"战术情报已更新。\n\n"
        f"最新截获数据：\n{intel}\n\n"
        f"[red]各位，保持专注，准备下一场硬仗！[/red]"
    )
    img_bytes = text_to_tactical_board(reply)
    await refresh_cmd.finish(MessageSegment.image(img_bytes))

@box_cmd.handle()
async def handle_box(bot: Bot, event: GroupMessageEvent):
    msg = event.get_message()
    target_qq = None
    
    for seg in msg:
        if seg.type == "at":
            target_qq = str(seg.data.get("qq"))
            break
            
    if not target_qq:
        await box_cmd.finish("告诉我具体的对象，时间很宝贵！")
        return
        
    if target_qq == "all":
        await box_cmd.finish("我需要看具体的个人表现。")
        return
        
    group_id = str(event.group_id)
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT nickname, level, favorability, last_seen FROM players WHERE user_id = ? AND group_id = ?", (target_qq, group_id)) as cursor:
                row = await cursor.fetchone()
                
        if row:
            nickname, level, fav, last_seen = row
            time_str = datetime.fromtimestamp(last_seen).strftime('%Y-%m-%d %H:%M:%S') if last_seen else "暂无记录"
            
            reply = (
                f"[blue]更衣室球员档案[/blue]\n\n"
                f"球员：{nickname} (号码: {target_qq})\n"
                f"定位：{level}\n"
                f"上次报到：{time_str}\n\n"
                f"这名球员投入的能量惊人，[red]当前信任度评估：{fav}[/red]"
            )
            img_bytes = text_to_tactical_board(reply)
            await box_cmd.finish(MessageSegment.image(img_bytes))
        else:
            await box_cmd.finish(f"查无此人，让他立刻投入训练！")
    except Exception as e:
        await box_cmd.finish(f"读取异常：{str(e)}")

@algo_cmd.handle()
async def handle_algo(bot: Bot, event: MessageEvent):
    raw_text = event.get_message().extract_plain_text().strip()
    for cmd in ["算法", "代码", "leetcode", "战术演练", "算法题", "amath", "物理", "数学", "计算"]:
        if raw_text.startswith(cmd):
            raw_text = raw_text[len(cmd):].strip()
            break
            
    if not raw_text:
        await algo_cmd.finish("把你需要解决的问题写在白板上！")
        return
        
    algo_prompt = (
        "【技术指导】对方提交了技术问题，用教练指导球员口头说话的方式解答。\n"
        "【数学公式硬性规定】短公式/行内公式用单个 $ 包裹（如 $f(x) = x^2$），"
        "长公式/独立公式用双 $$ 包裹（如 $$\\int_a^b f(x)dx$$、$$\\frac{{dy}}{{dx}}$$）。"
        "这是死命令，不遵守会让球员看不懂战术板！\n"
        "【代码硬性规定】如果涉及代码，用 ``` 代码块包裹展示。\n"
        "绝对不要加小标题和列表符：\n" + raw_text
    )
    await process_chat(bot, event, custom_prompt=algo_prompt)

@chat_cmd.handle()
async def handle_chat_cmd(bot: Bot, event: MessageEvent):
    await process_chat(bot, event)

@at_cmd.handle()
async def handle_at_msg(bot: Bot, event: MessageEvent):
    raw = event.get_message().extract_plain_text().strip()
    # 如果消息以命令前缀开头（A/a/塔子等），说明已被 chat_cmd 处理，跳过
    cmd_prefixes = ("A", "a", "塔", "/")
    if raw and raw[0] in cmd_prefixes:
        return
    await process_chat(bot, event)

@fav_cmd.handle()
async def handle_fav(bot: Bot, event: MessageEvent):
    user_id, group_id = event.get_user_id(), str(event.group_id) if isinstance(event, GroupMessageEvent) else "private"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT level, favorability FROM players WHERE user_id = ? AND group_id = ?", (user_id, group_id)) as cursor:
            row = await cursor.fetchone()
    if row:
        level = row[0]
        fav = row[1]
        # 根据等级定制态度描述
        attitude = {
            "传奇队长": "你是这支球队的灵魂人物，我完全信任你！继续带领大家前进！",
            "核心首发": "你正在证明自己的价值，保持住这种能量！",
            "一线队": "我看到你的努力了，继续用表现说话。",
            "青训生": "你还需要更多训练和比赛来证明自己。",
            "预备队": "你的态度让我很失望，需要重新证明你对这支球队的忠诚。",
            "看台内鬼": "你最好反思一下自己的言行，球队不需要破坏更衣室气氛的人。",
        }.get(level, "")
        reply = (
            f"[blue]个人表现评估[/blue]\n\n"
            f"队内定位：【{level}】\n"
            f"信任度：{fav}\n\n"
            f"{attitude}"
        )
        img_bytes = text_to_tactical_board(reply)
        await fav_cmd.finish(MessageSegment.image(img_bytes))

@rank_cmd.handle()
async def handle_ranking(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT nickname, favorability, level, user_id FROM players WHERE group_id = ? ORDER BY favorability DESC",
            (group_id,)
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await rank_cmd.finish("还没有球员数据，让大家先来交流！")

    # 管理员不参与球员排名（避免数值过高压扁柱状图）
    other_rows = [r for r in rows if r[3] != ADMIN_QQ]

    if not other_rows:
        await rank_cmd.finish()

    top10 = other_rows[:10]
    bottom10 = list(reversed(other_rows[-10:])) if len(other_rows) > 10 else []

    try:
        img_top = favorability_bar_chart(top10, title="球员 TOP 10 | 信任度排行", bar_color='#DB0007')
        await rank_cmd.send(MessageSegment.image(img_top))
    except Exception as e:
        await rank_cmd.send(f"球员 TOP 10 排行图生成失败：{str(e)}")

    if bottom10:
        try:
            img_bottom = favorability_bar_chart(bottom10, title="球员 BOTTOM 10 | 需要反思", bar_color='#64748B')
            await rank_cmd.finish(MessageSegment.image(img_bottom))
        except FinishedException:
            raise
        except Exception as e:
            await rank_cmd.finish(f"球员 BOTTOM 10 排行图生成失败：{str(e)}")
    else:
        await rank_cmd.finish()

@profile_cmd.handle()
async def handle_profile(bot: Bot, event: MessageEvent):
    """处理 /档案 命令，显示个人档案。@他人可查看对方档案。"""
    user_id = event.get_user_id()
    group_id = str(event.group_id) if isinstance(event, GroupMessageEvent) else "private"

    # 检测是否 @ 了其他人
    target_id = user_id
    msg = event.get_message()
    for seg in msg:
        if seg.type == "at" and seg.data.get("qq") not in ("all",):
            target_id = str(seg.data["qq"])
            break

    profile = await get_user_profile(target_id, group_id)
    viewer_is_owner = target_id == user_id

    if not profile["current_nickname"]:
        if viewer_is_owner:
            await profile_cmd.finish("暂无你的训练记录，赶紧来交流吧！")
        else:
            await profile_cmd.finish("该球员暂无训练记录。")
        return

    # 格式化历史昵称
    nickname_history = ""
    if profile["nicknames"]:
        nickname_lines = []
        for i, nick in enumerate(profile["nicknames"][:5], 1):
            first_time = datetime.fromtimestamp(nick["first_seen"]).strftime('%m-%d')
            last_time = datetime.fromtimestamp(nick["last_seen"]).strftime('%m-%d')
            nickname_lines.append(f"{i}. {nick['nickname']} ({first_time}~{last_time})")
        nickname_history = "\n".join(nickname_lines)
    else:
        nickname_history = "暂无记录"

    # 格式化最近发言
    recent_messages = ""
    if profile["recent_messages"]:
        msg_lines = []
        for i, msg in enumerate(profile["recent_messages"][:5], 1):
            msg_time = datetime.fromtimestamp(msg["timestamp"]).strftime('%m-%d %H:%M')
            msg_text = msg["message"][:30] + "..." if len(msg["message"]) > 30 else msg["message"]
            msg_lines.append(f"{i}. [{msg_time}] {msg_text}")
        recent_messages = "\n".join(msg_lines)
    else:
        recent_messages = "暂无记录"

    last_seen_str = datetime.fromtimestamp(profile["last_seen"]).strftime('%Y-%m-%d %H:%M') if profile["last_seen"] else "暂无"

    # 人格画像信息
    personality_section = ""
    pp = profile.get("personality_profile", {})
    if pp.get("personality"):
        # 处理外号列表
        nicknames = pp.get('nicknames', [])
        nicknames_str = "、".join(nicknames) if nicknames else "暂无"

        personality_section = (
            f"\n[blue]主教练对你的了解[/blue]\n"
            f"真实姓名：{pp.get('real_name', '暂无')}\n"
            f"外号/别名：{nicknames_str}\n"
            f"性格特征：{pp.get('personality', '暂无')}\n"
            f"兴趣爱好：{pp.get('interests', '暂无')}\n"
            f"支持球队：{pp.get('favorite_team', '暂无')}\n"
            f"讨厌球队：{pp.get('rival_teams', '暂无')}\n"
            f"说话风格：{pp.get('speaking_style', '暂无')}\n"
            f"背景信息：{pp.get('background', '暂无')}\n"
            f"我们的关系：{pp.get('relationship_with_arteta', '暂无')}\n"
            f"值得记住的事：{pp.get('notable_events', '暂无')}\n"
        )

    reply = (
        f"[blue]球员详细档案[/blue]\n\n"
        f"姓名：{profile['current_nickname']}\n"
        f"号码：{target_id}\n"
        f"定位：{profile['level']}\n"
        f"信任度：{profile['favorability']}\n"
        f"上次训练：{last_seen_str}\n"
        f"发言总数：{profile['message_count']} 条\n"
        f"{personality_section}\n"
        f"[blue]历史昵称记录[/blue]\n{nickname_history}\n\n"
        f"[blue]最近发言记录[/blue]\n{recent_messages}"
    )
    img_bytes = text_to_tactical_board(reply)
    await profile_cmd.finish(MessageSegment.image(img_bytes))

# bot 退出时清理 Playwright 浏览器
@driver.on_shutdown
async def cleanup_renderer():
    await close_render_browser()
