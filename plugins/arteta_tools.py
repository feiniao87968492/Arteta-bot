"""Function Calling 工具函数定义和执行器"""

import httpx
import asyncio
import json
import sqlite3
import time
from datetime import datetime

from typing import List
from plugins.arteta_knowledge import query_knowledge

DB_PATH = __import__("os").environ.get("ARTETA_DB_PATH", "arsenal_data.db")

# --- 配置（在运行时由 register_config() 注入）---
FOOTBALL_API_TOKEN = ""
DEEPSEEK_API_KEY = ""
DEEPSEEK_API_URL = "https://www.boxying.com/v1/chat/completions"
DEEPSEEK_MODEL = "gpt-5.5"
DEEPSEEK_TEMPERATURE = 0.9
ARSENAL_ID = 57
HAS_WEB_SEARCH = False


def _coerce_temperature(value, default=0.9):
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(2.0, temperature))


def register_config(**kwargs):
    """在 bot 启动时注入全局配置"""
    global FOOTBALL_API_TOKEN, DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_MODEL, DEEPSEEK_TEMPERATURE, ARSENAL_ID, HAS_WEB_SEARCH
    FOOTBALL_API_TOKEN = kwargs.get("football_api_token", "")
    DEEPSEEK_API_KEY = kwargs.get("deepseek_api_key", "")
    DEEPSEEK_API_URL = kwargs.get("deepseek_api_url", "https://www.boxying.com/v1/chat/completions")
    DEEPSEEK_MODEL = kwargs.get("deepseek_model", "gpt-5.5")
    DEEPSEEK_TEMPERATURE = _coerce_temperature(kwargs.get("deepseek_temperature", 0.9))
    ARSENAL_ID = kwargs.get("arsenal_id", 57)
    HAS_WEB_SEARCH = kwargs.get("has_web_search", False)


FOOTBALL_NEWS_CATEGORY_KEYWORDS = [
    ("premier_league", ["英超", "曼联", "曼城", "利物浦", "切尔西", "热刺", "阿森纳"]),
    ("champions_league", ["欧冠", "冠军杯", "冠军联赛"]),
    ("laliga", ["西甲", "皇马", "巴萨", "马竞"]),
    ("serie_a", ["意甲", "尤文", "国米", "米兰", "罗马", "那不勒斯"]),
    ("bundesliga", ["德甲", "拜仁", "多特", "勒沃库森"]),
    ("ligue1", ["法甲", "巴黎", "马赛", "里昂", "摩纳哥"]),
    ("chinese_super_league", ["中超", "国安", "申花", "海港", "泰山", "蓉城"]),
]


def detect_football_news_query(query: str):
    text = query or ""
    image_question_keywords = ["这张图", "这个图", "图片", "图里", "截图", "照片", "看图", "图讲", "图说"]
    if any(word in text for word in image_question_keywords):
        return None
    if not any(word in text for word in ["新闻", "消息", "动态", "最近", "最新", "怎么样", "有什么"]):
        return None
    for category, keywords in FOOTBALL_NEWS_CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return text, category
    if "五大联赛" in text or "足球" in text:
        return text, None
    return None


async def maybe_search_football_news_for_prompt(query: str) -> str:
    return ""


def format_football_news_direct_answer(query: str, search_result: str) -> str:
    if not search_result or "没有找到符合时间范围" in search_result or "尚未初始化" in search_result or "检索失败" in search_result:
        return "教练查了本地足球新闻库，这个分类最近还没有可靠新闻入库。\n\n【好感度=】"
    lines = [line.strip() for line in search_result.splitlines() if line.strip()]
    highlights = lines[:5]
    body = "教练刚查了本地足球新闻库，最新能看到这些：\n\n" + "\n".join(highlights)
    body += "\n\n重点是：这些是已经同步进本地向量库的新闻，不是我凭印象编的。"
    body += "\n\n【好感度+】"
    return body


async def maybe_answer_football_news_directly(query: str) -> str:
    return ""


# --- 工具定义（DeepSeek / OpenAI 格式）---
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_arsenal_result",
            "description": "获取阿森纳最近比赛结果（比分、对手、赛事）。当用户问比赛结果、比分、赢没赢时调用",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pl_table",
            "description": "获取当前英超积分榜（前几名和后几名排名、积分）。当用户问排名、积分榜、争冠形势时调用",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_arsenal_injuries",
            "description": "获取阿森纳最新伤病信息。当用户问某球员是否受伤、伤愈复出时间、伤病名单时调用",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": "搜索足球/转会/阿森纳相关最新新闻。当用户问转会传闻、签约、官宣、联赛动态时调用。搜索词请用英文",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {
                        "type": "string",
                        "description": "英文搜索关键词，如 'Arsenal transfer news', 'Premier League results'"
                    }
                },
                "required": ["q"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_football_knowledge",
            "description": "查询阿尔特塔的知识库（含阿森纳当前一线队球员名单、战术概念、更衣室故事、发布会语录、足球哲学）。当你需要查询球员信息、当前阵容、球员名单、球队新闻、战术术语、球队哲学时调用",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "要查询的主题关键词，如'灯泡演讲'、'内收型边后卫'、'信任'、'process'等"
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_group_members",
            "description": "获取群内活跃球员名单（近24小时有发言的）。包含昵称、身份定位、好感度、发言数。当你想了解更衣室里有谁、群内当前活跃球员、或提到某个球员时需要调用",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "string",
                        "description": "群号，从系统信息中获取"
                    }
                },
                "required": ["group_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_member_relations",
            "description": "查询某位球员在群内经常和谁互动（回复/@最多的人）。当你想了解球员之间的社交关系、谁和谁关系好、或者提起某位球员想连带提到他朋友时调用",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "string",
                        "description": "群号"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "要查询的球员QQ号"
                    }
                },
                "required": ["group_id", "user_id"]
            }
        }
    }
]


# --- 工具执行器 ---

async def call_deepseek_tool(messages: List[dict]) -> List[dict]:
    """单次调用 DeepSeek，返回完整响应 messages（含可能的 tool_calls）"""
    async with httpx.AsyncClient(timeout=80.0) as client:
        resp = await client.post(
            DEEPSEEK_API_URL,
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            json={
                "model": DEEPSEEK_MODEL,
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "temperature": DEEPSEEK_TEMPERATURE
            }
        )
        if resp.status_code != 200:
            raise Exception(f"DeepSeek API error: {resp.status_code} {resp.text[:200]}")

        choice = resp.json()["choices"][0]
        msg = choice["message"]

        result_messages = [{"role": msg["role"], "content": msg.get("content", "")}]

        if "tool_calls" in msg and msg["tool_calls"]:
            result_messages[0]["tool_calls"] = msg["tool_calls"]

        # DeepSeek thinking mode：reasoning_content 必须在后续请求中原样传回
        if "reasoning_content" in msg and msg["reasoning_content"]:
            result_messages[0]["reasoning_content"] = msg["reasoning_content"]

        return result_messages


async def execute_tool_call(tc: dict) -> str:
    """执行单个 tool call，返回结果字符串"""
    name = tc["function"]["name"]
    try:
        args = json.loads(tc["function"]["arguments"])
    except json.JSONDecodeError:
        args = {}

    if name == "get_arsenal_result":
        return await _get_arsenal_result()
    elif name == "get_pl_table":
        return await _get_pl_table()
    elif name == "get_arsenal_injuries":
        return await _get_arsenal_injuries()
    elif name == "search_news":
        return await _search_news(args.get("q", ""))
    elif name == "get_football_knowledge":
        return query_knowledge(args.get("topic", ""), max_chars=3000)
    elif name == "get_group_members":
        return await _get_group_members(args.get("group_id", ""))
    elif name == "get_member_relations":
        return await _get_member_relations(args.get("group_id", ""), args.get("user_id", ""))
    else:
        return f"未知工具: {name}"


async def run_tool_loop(user_messages: List[dict]) -> str:
    """完整的 function calling 循环：
    1. 发送消息 + tools
    2. 如果返回 tool_calls，执行工具
    3. 把结果送回给 LLM
    4. 重复直到 LLM 返回自然语言回复
    """
    messages = list(user_messages)

    for _ in range(5):  # 最多 5 轮 tool call
        resp_msgs = await call_deepseek_tool(messages)
        messages.extend(resp_msgs)

        last = resp_msgs[-1]
        if "tool_calls" not in last or not last["tool_calls"]:
            content = (last.get("content") or "").strip()
            if content:
                return content
            messages.append({"role": "user", "content": "请直接给出最终回复，不要返回空内容。"})
            continue

        # 执行所有 tool call
        for tc in last["tool_calls"]:
            result = await execute_tool_call(tc)
            print(f"[Tool] {tc['function']['name']} -> {result[:100]}...")
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result
            })

    # 超过 5 轮强制返回
    return messages[-1].get("content", "让我整理一下思路再回答你。")


# --- 具体工具实现 ---

async def _get_arsenal_result() -> str:
    """获取阿森纳最近比赛结果"""
    headers = {"X-Auth-Token": FOOTBALL_API_TOKEN}
    lines = []

    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            res = await client.get(
                f"https://api.football-data.org/v4/teams/{ARSENAL_ID}/matches?status=FINISHED",
                headers=headers
            )
            if res.status_code == 200:
                matches = res.json().get("matches", [])
                for m in matches[-3:]:
                    comp = m["competition"]["name"]
                    home = m["homeTeam"]["shortName"]
                    away = m["awayTeam"]["shortName"]
                    date = m["utcDate"][:10]
                    sh = m["score"]["fullTime"]["home"]
                    sa = m["score"]["fullTime"]["away"]
                    if sh is None:
                        sh = m["score"].get("regularTime", {}).get("home", 0)
                        sa = m["score"].get("regularTime", {}).get("away", 0)
                    lines.append(f"阿森纳({date} {comp})：{home} {sh}:{sa} {away}")
            else:
                lines.append(f"[API Error: {res.status_code}]")
    except Exception as e:
        lines.append(f"[Data Error: {e}]")

    return "\n".join(lines) if lines else "暂无数据"


async def _get_pl_table() -> str:
    """获取英超积分榜"""
    headers = {"X-Auth-Token": FOOTBALL_API_TOKEN}
    lines = []

    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            res = await client.get(
                "https://api.football-data.org/v4/competitions/PL/standings",
                headers=headers
            )
            if res.status_code == 200:
                table = res.json()["standings"][0]["table"]
                for team in table:
                    pos = team["position"]
                    name = team["team"]["shortName"]
                    pts = team["points"]
                    tid = team["team"]["id"]
                    if pos <= 4 or tid == ARSENAL_ID or pos >= 18:
                        lines.append(f"第{pos}名 {name} {pts}分")
                return "\n".join(lines)
            else:
                return f"[API Error: {res.status_code}]"
    except Exception as e:
        return f"[Data Error: {e}]"


async def _get_arsenal_injuries() -> str:
    """通过 DuckDuckGo 搜索伤病信息（英文搜索）"""
    if not HAS_WEB_SEARCH:
        return "搜索功能不可用。"

    try:
        from duckduckgo_search import DDGS

        def _search():
            with DDGS(headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}) as ddgs:
                return list(ddgs.text("Arsenal injury news latest squad updates", max_results=3))

        results = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _search),
            timeout=5.0
        )

        snippets = []
        for r in results:
            t = r.get("title", "").strip()
            b = r.get("body", "").strip()[:200]
            if t or b:
                snippets.append(f"• {t}：{b}" if t else f"• {b}")

        return "\n".join(snippets) if snippets else "未找到相关伤病信息。"
    except asyncio.TimeoutError:
        return "[搜索超时]"
    except Exception as e:
        print(f"[Tool Error] _get_arsenal_injuries: {e}")
        return f"[搜索失败]"


async def _search_news(q: str) -> str:
    """搜索最新新闻（英文搜索词）"""
    if not HAS_WEB_SEARCH or not q:
        return "搜索功能不可用或关键词为空。"

    try:
        from duckduckgo_search import DDGS

        def _search():
            with DDGS(headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}) as ddgs:
                return list(ddgs.text(q, max_results=5))

        results = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _search),
            timeout=5.0
        )

        snippets = []
        for r in results:
            t = r.get("title", "").strip()
            b = r.get("body", "").strip()[:200]
            if t or b:
                snippets.append(f"• {t}：{b}" if t else f"• {b}")

        return "\n".join(snippets) if snippets else "未找到相关信息。"
    except asyncio.TimeoutError:
        return "[搜索超时]"
    except Exception as e:
        print(f"[Tool Error] _search_news: {e}")
        return "[搜索失败]"


async def _search_football_news(query: str, category=None, days: int = 14) -> str:
    """查询本地足球新闻向量库。"""
    try:
        from plugins.arteta_football_news import FootballNewsChromaStore, FootballNewsSQLiteStore, CHROMA_DB_DIR, DB_PATH
        from plugins.arteta_football_intelligence.models import FootballKnowledgeQuery
        from plugins.arteta_football_intelligence.query import query_current_football_knowledge
        try:
            safe_days = int(days)
        except (TypeError, ValueError):
            safe_days = 14
        category_value = str(category).strip() if category else None
        sqlite_store = FootballNewsSQLiteStore(DB_PATH)
        sqlite_store.initialize()
        result = query_current_football_knowledge(
            sqlite_store,
            FootballKnowledgeQuery(
                query=str(query or ""),
                competitions=[category_value] if category_value else [],
                max_age_seconds=max(1, safe_days) * 86400,
                max_results=8,
            ),
        )
        if result.items:
            lines = []
            for item in result.items:
                date_text = datetime.fromtimestamp(int(item.fetched_at or item.published_at or 0)).strftime("%Y-%m-%d")
                lines.append("• [%s] %s｜%s｜%s｜%s" % (
                    date_text,
                    item.title,
                    item.source_name,
                    item.summary[:180],
                    item.canonical_url,
                ))
            return "\n".join(lines)
        store = FootballNewsChromaStore(CHROMA_DB_DIR)
        store.initialize()
        return store.search(query=query, category=category_value, days=safe_days)
    except Exception as e:
        print(f"[Tool Error] _search_football_news: {e}")
        return "足球新闻库暂时不可用。"


async def _get_group_members(group_id: str) -> str:
    """获取群内活跃球员名单（近24h有发言的）"""
    if not group_id:
        return "请提供群号。"
    try:
        conn = sqlite3.connect(DB_PATH)
        cutoff = int(time.time()) - 86400
        rows = conn.execute("""
            SELECT p.nickname, p.level, p.favorability, COUNT(m.id) as msg_count
            FROM players p
            LEFT JOIN messages m ON p.user_id = m.user_id AND p.group_id = m.group_id AND m.timestamp > ?
            WHERE p.group_id = ?
            GROUP BY p.user_id
            HAVING msg_count > 0
            ORDER BY msg_count DESC
            LIMIT 20
        """, (cutoff, group_id)).fetchall()
        conn.close()

        if not rows:
            return "该群暂无活跃球员数据。"

        lines = [f"【{group_id}】活跃球员（近24h）："]
        for nick, lvl, fav, count in rows:
            lines.append(f"• {nick} | {lvl} | 好感度{fav} | 发言{count}次")
        return "\n".join(lines)
    except Exception as e:
        return f"[查询失败: {e}]"


async def _get_member_relations(group_id: str, user_id: str) -> str:
    """查询某位球员互动最多的群成员"""
    if not group_id or not user_id:
        return "请提供群号和球员QQ号。"
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("""
            SELECT r.target_user_id, p.nickname, r.interaction_count
            FROM member_relations r
            LEFT JOIN players p ON r.target_user_id = p.user_id AND p.group_id = r.group_id
            WHERE r.user_id = ? AND r.group_id = ?
            ORDER BY r.interaction_count DESC
            LIMIT 8
        """, (user_id, group_id)).fetchall()

        # 同时也查反向：谁在跟这位球员互动
        reverse = conn.execute("""
            SELECT r.user_id, p.nickname, r.interaction_count
            FROM member_relations r
            LEFT JOIN players p ON r.user_id = p.user_id AND p.group_id = r.group_id
            WHERE r.target_user_id = ? AND r.group_id = ?
            ORDER BY r.interaction_count DESC
            LIMIT 5
        """, (user_id, group_id)).fetchall()
        conn.close()

        parts = []
        if rows:
            parts.append("→ 他经常互动的人：")
            for tid, tnick, cnt in rows:
                parts.append(f"  • {tnick or tid}（{cnt}次）")
        if reverse:
            parts.append("→ 经常找他互动的人：")
            for rid, rnick, cnt in reverse:
                parts.append(f"  • {rnick or rid}（{cnt}次）")

        if not parts:
            return "暂无该球员的互动数据。"
        return "\n".join(parts)
    except Exception as e:
        return f"[查询失败: {e}]"
