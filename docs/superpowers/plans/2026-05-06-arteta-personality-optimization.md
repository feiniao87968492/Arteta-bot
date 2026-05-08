# 阿尔特塔机器人人格优化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 解决机器人过度强调比赛、端水、重复老故事的问题，通过 Function Calling + 本地知识库 + Prompt 重构三管齐下。

**Architecture:** 
- `plugins/arteta_tools.py` — 封装 5 个 DeepSeek tool，供 LLM 按需调用获取赛果/积分/伤病/新闻/知识
- `plugins/arteta_knowledge.py` — 本地知识库检索引擎，关键词匹配返回内容摘要
- `plugins/arteta_chat.py` — 修改 `process_chat()`，加入 function calling 循环；重写 `ARTETA_PROMPT`

**Tech Stack:** DeepSeek API (function calling), DuckDuckGo (搜索), football-data.org (赛果/积分), 本地 markdown 文件 (知识库)

---

### Task 1: 创建知识库引擎 `arteta_knowledge.py`

**Files:**
- Create: `plugins/arteta_knowledge.py`
- Create: `knowledge_base/glossary.md`
- Create: `knowledge_base/documentary/01-locker-room-speeches.md`
- Create: `knowledge_base/tactics/01-inverted-fullback.md`
- Create: `knowledge_base/press/01-classic-quotes.md`
- Create: `knowledge_base/philosophy/01-trust-the-process.md`

- [ ] **Step 1: 创建知识库目录和初始文件**

```bash
mkdir -p "D:/Users/zty/arteta_bot/knowledge_base/documentary"
mkdir -p "D:/Users/zty/arteta_bot/knowledge_base/tactics"
mkdir -p "D:/Users/zty/arteta_bot/knowledge_base/press"
mkdir -p "D:/Users/zty/arteta_bot/knowledge_base/philosophy"
```

- [ ] **Step 2: 写 glossary 初始内容**

Write `knowledge_base/glossary.md`:
```markdown
# 战术术语表

## 内收型边后卫 (Inverted Fullback)
边后卫在进攻时内收到中场中路，形成中场人数优势。津琴科是典型代表。
阿尔特塔体系的基石之一——让边后卫在中路参与组织，边路宽度留给边锋。

## 2-3-5 进攻站位
进攻时阵型变为 2-3-5：两名中后卫拖后，一名后腰+两名内收边后卫组成中场三人组，
五名前锋占据前场宽度和肋部空当。

## 高位逼抢 (High Press / Gegenpress)
失去球权后 5 秒内立即在前场施压反抢，不让对手舒服出球。
阿尔特塔要求"在对手思考之前就夺回球权"。

## 第 6 人 (The Sixth Man)
指进攻时中场球员插入禁区成为额外接应点——通常由厄德高或哈弗茨担任。
打破防线平衡的关键：让后卫不知道该盯谁。

## 肋部 (Half-space)
边后卫和中后卫之间的区域，现代足球最具威胁的进攻发起区域。
阿尔特塔的进攻高度依赖球员在肋部接球和转身。

## 能量 (Energy)
阿尔特塔最常挂在嘴边的词。不只是跑动距离，更是"带着意图的跑动"——压迫时机、前插时机、集体移动的同步性。

## 连线 (Connection)
球员之间的默契、场上位置的呼应、更衣室内的信任。阿尔特塔相信"connected"的团队能爆发超常能量。
```

- [ ] **Step 3: 写 documentry 初始内容（灯泡演讲 + 大脑心脏演讲移入知识库）**

Write `knowledge_base/documentary/01-locker-room-speeches.md`:
```markdown
# 更衣室经典演讲

## 灯泡演讲 (Lightbulb Speech)
来源：All or Nothing 纪录片，2022 年赛季前
场景：赛前更衣室，阿尔特塔拿了一个灯泡走进来
原文风格：
「爱迪生发明了灯泡。今天我要看到一支 connected 的队伍，因为一个灯泡本身什么都不是。
你们要互相传递光芒和能量、激情，然后和场上六万名球迷 connected，产生更多的能量——最终是电，
通过热产生光、产生生命！我们有多优秀取决于一件事，让我们特别的是我们的态度。
今天我要你们上场，把灯给我打开！」

## 大脑与心脏演讲 (Brain & Heart)
来源：All or Nothing 纪录片
场景：白板上的涂鸦——一个卡通大脑和一颗心脏手拉手
核心思想：
「我们要用大心脏踢球，同时也要用大脑踢球。这两者必须协同工作。
激情，是你们付出多少、投入多少。但对手会挑衅你们——你要始终保持 control，
做决定的时候、换挡变速的时候，你不能整场比赛都以十万英里的时速狂奔。」

## 标准与底线训话 (Standards Speech)
来源：All or Nothing 纪录片，0-3 开局后在更衣室
核心思想：
「很多行业都有高绩效团队，他们有一个共同点——他们出结果。我也有过恐惧、不安，
媒体都在骂我。但突然之间，我看到了所有的可能性——我有一个了不起的家庭、这个伟大的俱乐部。
而让我从负二跃升到十分情绪的，是你们。相信自己，我相信你们。我不想在困难时刻指责你们任何人。」
```

- [ ] **Step 4: 写 tactics 初始内容**

Write `knowledge_base/tactics/01-inverted-fullback.md`:
```markdown
# 内收型边后卫 (Inverted Fullback)

## 基本概念
传统边后卫沿边路插上助攻；内收型边后卫在进攻时内切到中场中路，参与组织。

## 在阿尔特塔体系中的作用
1. **人数优势**：边后卫内收后，中场从 2 人变成 3-4 人，形成局部人数优势
2. **边路宽度交给边锋**：萨卡/马丁内利占据边路，边后卫在中路提供传球选项
3. **对手防守困惑**：对手不知道是该跟防内收的边后卫还是留在边路

## 代表球员
- 津琴科 (Zinchenko)：传射俱佳，但防守有隐患
- 蒂尔尼 (Tierney)：传统边后卫，不适应内收打法后被边缘化
- 富安健洋 (Tomiyasu)：能内收也能传统防守，战术适配性强

## 阿尔特塔原话风格
"我需要 full-back 不仅仅会套边插上，还要能阅读比赛——什么时候内收，什么时候拉开，
什么时候前插到禁区。这不是机械的跑位，这是对比赛的理解。"
```

- [ ] **Step 5: 写 press 初始内容**

Write `knowledge_base/press/01-classic-quotes.md`:
```markdown
# 经典发布会语录

## 关于转会传闻
"我不评论其他俱乐部的球员。"
"我们一直在关注市场，但最重要的是我们现在拥有的球员。"

## 关于信任
"我完全信任我的球员。"
"我看到他们每天在训练场上的付出，这就是我为什么对他们有信心。"

## 关于比赛态度
"我们想赢下每一场比赛。"
"今天我们展现了正确的态度，但还有需要改进的地方。"
"能量和激情是我们 DNA 的一部分。"

## 关于 process
"Trust the process。我们走在正确的道路上。"
"重要的是我们每天都在进步，而不是短期结果。"
```

- [ ] **Step 6: 写 philosophy 初始内容**

Write `knowledge_base/philosophy/01-trust-the-process.md`:
```markdown
# 阿尔特塔的足球哲学

## 核心理念
1. **控制 (Control)**：不只要控球，更要控制比赛节奏和情绪
2. **集体大于个人 (The Team > The Individual)**：没有人高于球队
3. **持续进步 (Continuous Improvement)**：每场比赛都要比上一场更好
4. **高标准 (High Standards)**：训练、饮食、作息——每个环节都有要求

## 关于球员发展
"我不是只想赢下下一场比赛，我要帮助这些球员成为更好的自己。"
"年轻球员需要机会，但机会来自于训练中的表现。"

## 关于比赛风格
"我想让阿森纳成为一支对手都不想面对的球队。"
"我们要踢出让人兴奋的足球，但同时也要保持稳固。"
```

- [ ] **Step 7: 创建 `arteta_knowledge.py`**

Write `plugins/arteta_knowledge.py`:
```python
"""本地知识库检索引擎"""

import os
import re
from pathlib import Path

KNOWLEDGE_BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge_base")

# 文件缓存：避免每次查询都读磁盘
_file_cache: dict[str, str] = {}
_cache_loaded = False


def _load_all_files():
    """加载知识库所有 .md 文件到缓存"""
    global _cache_loaded
    if _cache_loaded:
        return
    kb_path = Path(KNOWLEDGE_BASE_DIR)
    if not kb_path.exists():
        _cache_loaded = True
        return
    for fpath in kb_path.rglob("*.md"):
        try:
            _file_cache[str(fpath.relative_to(kb_path))] = fpath.read_text(encoding="utf-8")
        except Exception:
            pass
    _cache_loaded = True


def query_knowledge(topic: str, max_chars: int = 1500) -> str:
    """根据主题关键词检索知识库，返回匹配的内容摘要。
    
    Args:
        topic: 搜索主题（中文关键词，如"边后卫""灯泡演讲""信任"）
        max_chars: 返回内容上限
        
    Returns:
        匹配的知识片段，无匹配时返回空字符串
    """
    _load_all_files()
    if not _file_cache:
        return ""
    
    topic_lower = topic.lower()
    
    # 评分：按关键词匹配度给分
    scored: list[tuple[int, str, str]] = []  # (score, filename, content)
    
    for fname, content in _file_cache.items():
        content_lower = content.lower()
        score = 0
        
        # 文件名匹配（权重高）
        if topic_lower in fname.lower():
            score += 10
        
        # 在内容中的匹配次数
        matches = content_lower.count(topic_lower)
        score += matches * 2
        
        # ## 标题匹配（权重更高）
        for line in content.split("\n"):
            if line.startswith("##") and topic_lower in line.lower():
                score += 5
            if line.startswith("#") and topic_lower in line.lower():
                score += 3
        
        if score > 0:
            scored.append((score, fname, content))
    
    if not scored:
        return ""
    
    # 按分数降序
    scored.sort(key=lambda x: x[0], reverse=True)
    
    # 返回最高分的文件内容摘要
    _, fname, content = scored[0]
    header = f"[知识来源：{fname}]\n"
    
    if len(content) <= max_chars:
        return header + content
    
    # 截取匹配段落附近的文本
    paragraphs = content.split("\n\n")
    topic_paragraphs = []
    remained = max_chars - len(header)
    for para in paragraphs:
        if topic_lower in para.lower():
            if len(para) <= remained:
                topic_paragraphs.append(para)
                remained -= len(para)
            else:
                topic_paragraphs.append(para[:remained])
                break
    
    if topic_paragraphs:
        return header + "\n\n".join(topic_paragraphs)
    else:
        return header + content[:max_chars]


def get_knowledge_file_list() -> list[str]:
    """返回知识库文件列表（供调试/查看用）"""
    _load_all_files()
    return sorted(_file_cache.keys())
```

- [ ] **Step 8: 本地验证**

```bash
cd /d/Users/zty/arteta_bot
# 测试导入和查询
python -c "
from plugins.arteta_knowledge import query_knowledge
result = query_knowledge('灯泡')
print('Query result length:', len(result))
print('First 200 chars:', result[:200])
"
```

Expected: 正确输出知识库文件内容

- [ ] **Step 9: Commit**

```bash
git add plugins/arteta_knowledge.py knowledge_base/
git commit -m "feat: add local knowledge base engine with initial Arsenal content"
```

---

### Task 2: 创建工具函数模块 `arteta_tools.py`

**Files:**
- Create: `plugins/arteta_tools.py`

- [ ] **Step 1: 创建 `arteta_tools.py`**

Write `plugins/arteta_tools.py`:
```python
"""Function Calling 工具函数定义和执行器"""

import httpx
import asyncio
import json
import time
from datetime import datetime
from typing import Any

from plugins.arteta_knowledge import query_knowledge

# --- 配置（从 arteta_chat 全局变量引用）---
# 这些在运行时由 register_tools() 设置
FOOTBALL_API_TOKEN = ""
DEEPSEEK_API_KEY = ""
ARSENAL_ID = 57
HAS_WEB_SEARCH = False

# 缓存
tactical_cache: dict[str, Any] = {"report": "", "last_update": 0}


def register_config(**kwargs):
    """在 bot 启动时注入全局配置"""
    global FOOTBALL_API_TOKEN, DEEPSEEK_API_KEY, ARSENAL_ID, HAS_WEB_SEARCH
    FOOTBALL_API_TOKEN = kwargs.get("football_api_token", "")
    DEEPSEEK_API_KEY = kwargs.get("deepseek_api_key", "")
    ARSENAL_ID = kwargs.get("arsenal_id", 57)
    HAS_WEB_SEARCH = kwargs.get("has_web_search", False)


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
            "description": "查询阿尔特塔的战术知识库。当你需要引用具体战术概念（如内收型边后卫、高位逼抢、2-3-5进攻站位）、更衣室故事（灯泡演讲、大脑与心脏演讲）、发布会语录或足球哲学时调用",
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
    }
]


# --- 工具执行器 ---

async def call_deepseek_tool(messages: list[dict]) -> list[dict]:
    """单次调用 DeepSeek，返回完整响应 messages（含可能的 tool_calls）"""
    async with httpx.AsyncClient(timeout=80.0) as client:
        resp = await client.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            json={
                "model": "deepseek-v4-flash",
                "messages": messages,
                "tools": TOOLS,
                "tool_choice": "auto"
            }
        )
        if resp.status_code != 200:
            raise Exception(f"DeepSeek API error: {resp.status_code} {resp.text[:200]}")
        
        choice = resp.json()["choices"][0]
        msg = choice["message"]
        
        result_messages = [{"role": msg["role"], "content": msg.get("content", "")}]
        
        if "tool_calls" in msg and msg["tool_calls"]:
            result_messages[0]["tool_calls"] = msg["tool_calls"]
        
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
        return query_knowledge(args.get("topic", ""))
    else:
        return f"未知工具: {name}"


async def run_tool_loop(user_messages: list[dict]) -> str:
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
            # LLM 返回了最终回复
            return last.get("content", "")
        
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
            # 已结束比赛
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
            with DDGS() as ddgs:
                return list(ddgs.text("Arsenal injury news latest squad updates", max_results=3))
        
        results = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _search),
            timeout=10.0
        )
        
        snippets = []
        for r in results:
            t = r.get("title", "").strip()
            b = r.get("body", "").strip()[:200]
            if t or b:
                snippets.append(f"• {t}：{b}" if t else f"• {b}")
        
        return "\n".join(snippets) if snippets else "未找到相关伤病信息。"
    except Exception as e:
        return f"[搜索失败: {e}]"


async def _search_news(q: str) -> str:
    """搜索最新新闻（英文搜索词）"""
    if not HAS_WEB_SEARCH or not q:
        return "搜索功能不可用或关键词为空。"
    
    try:
        from duckduckgo_search import DDGS
        
        def _search():
            with DDGS() as ddgs:
                return list(ddgs.text(q, max_results=5))
        
        results = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _search),
            timeout=10.0
        )
        
        snippets = []
        for r in results:
            t = r.get("title", "").strip()
            b = r.get("body", "").strip()[:200]
            if t or b:
                snippets.append(f"• {t}：{b}" if t else f"• {b}")
        
        return "\n".join(snippets) if snippets else "未找到相关信息。"
    except Exception as e:
        return f"[搜索失败: {e}]"
```

- [ ] **Step 2: 本地验证**

```bash
cd /d/Users/zty/arteta_bot
python -c "
from plugins.arteta_tools import TOOLS, query_knowledge
print(f'Tools count: {len(TOOLS)}')
result = query_knowledge('灯泡')
print(f'Knowledge query: {result[:100]}')
"
```

Expected: 正确导入模块，显示 5 个工具定义

- [ ] **Step 3: Commit**

```bash
git add plugins/arteta_tools.py
git commit -m "feat: add function calling tools module with 5 tools"
```

---

### Task 3: 集成 Function Calling 到 `process_chat()`

**Files:**
- Modify: `plugins/arteta_chat.py`

- [ ] **Step 1: 在 arteta_chat.py 添加 import 和 config 注入**

在文件顶部 import 区块添加（约第 23 行后）：

```python
from plugins.arteta_tools import (
    TOOLS as ARTETA_TOOLS,
    register_config as register_tools_config,
    run_tool_loop,
    call_deepseek_tool,
    execute_tool_call,
)
```

在 `init_db_safely()` 调用之后（约第 422 行后），添加配置注入：

```python
# 注入工具模块配置
register_tools_config(
    football_api_token=FOOTBALL_API_TOKEN,
    deepseek_api_key=DEEPSEEK_API_KEY,
    arsenal_id=ARSENAL_ID,
    has_web_search=HAS_WEB_SEARCH,
)
```

- [ ] **Step 2: 修改 `process_chat()` 函数**

将现有 `process_chat()` 中从 `# 构建 prompt` 到 LLM 调用的部分替换为 function calling 版本。

找到 `final_prompt` 构建部分（约第 1078 行），替换为：

```python
    # --- Function Calling 版本 ---
    base_prompt = (
        f"{ARTETA_PROMPT}\n\n"
        f"【背景信息】：\n当前时间：{current_time}\n{quoted_text}{img_analysis}\n"
        f"当前提问球员：{nickname}，身份：{lvl}，当前信任度：{fav}。\n"
        f"{profile_section}\n"
        f"【信任度态势】本次对话导致信任度{fav_status}了 {abs(inc)} 点（原因：{reason}）。\n"
        f"【个性化回复要求】：根据你对该球员的了解，调整你的回复风格和态度。"
        f"如果他是热刺球迷，可以适当调侃；如果他是忠实枪迷，给予更多鼓励；"
        f"如果他说话风格粗鲁，你可以严厉一些；如果他礼貌认真，你也可以更温和。"
        f"表现出你记得和这名球员之间的过往互动。"
    )
    
    if user_id not in user_memories:
        user_memories[user_id] = deque(maxlen=4)
    
    messages = [{"role": "system", "content": base_prompt}]
    messages.extend(list(user_memories[user_id]))
    
    user_message = prompt
    if quoted_text:
        user_message = f"{prompt}\n\n【引用的消息】：{quoted_text.replace('【引用消息链（由旧到新）】：', '').strip()}"
    
    messages.append({"role": "user", "content": user_message})
    
    try:
        answer = await run_tool_loop(messages)
        
        if answer:
            with open("/tmp/debug.log", "a") as df:
                df.write(f"FC answer (first 500): {answer[:500]}\n")
            user_memories[user_id].append({"role": "user", "content": user_message})
            user_memories[user_id].append({"role": "assistant", "content": answer})
            
            # 渲染（与现有逻辑相同）
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
        else:
            await bot.send(event, Message("让我想想再回答你。"))
    except Exception as e:
        await bot.send(event, Message(f"连接中断：{str(e)}"))
```

同时，移除不再需要的函数调用行——移除 `match_intel = await fetch_global_intel()`（约第 1055 行）以及 `intel_section` 的构建和拼接（第 1072-1076 行），因为现在这些数据由 LLM 通过 function calling 按需获取。

但注意：`fetch_global_intel()` 仍然被 `handle_refresh`（第 1169 行）和可能的其他逻辑使用，所以不要删除函数本身，只移除 `process_chat()` 中对它的调用。

- [ ] **Step 3: 验证语法**

```bash
cd /d/Users/zty/arteta_bot
python -c "import plugins.arteta_tools; import plugins.arteta_knowledge; print('Syntax OK')"
python -m py_compile plugins/arteta_chat.py && echo "arteta_chat.py syntax OK"
```

Expected: 所有模块语法检查通过

- [ ] **Step 4: Commit**

```bash
git add plugins/arteta_chat.py
git commit -m "feat: integrate function calling into process_chat, replace passive data injection"
```

---

### Task 4: 重写 ARTETA_PROMPT

**Files:**
- Modify: `plugins/arteta_chat.py`（替换 ARTETA_PROMPT 常量 + 移除 final_prompt 中的 6 级表格）

- [ ] **Step 1: 替换 ARTETA_PROMPT**

将第 75-94 行的 ARTETA_PROMPT 替换为：

```python
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
    "如果需要引用具体战术概念或更衣室故事，请使用 get_football_knowledge 工具获取准确资料。\n"
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
    "3. 信任度标注：在回复最后，用 [red] 标签宣告信任度变动"
    "（如：[red]你的信任度上升了 1 点。[/red]）。\n"
    "4. 【数学公式】：短/行内公式用单个 $ 包裹（如 $f(x)=x^2$），"
    "长/独立公式用双 $$ 包裹。\n"
    "5. 【代码】：如果涉及代码，用 ``` ``` 包裹展示。"
)
```

- [ ] **Step 2: 移除 final_prompt 中的 6 级回复表格**

在 Task 3 Step 2 的 `base_prompt` 中，已经移除了原有 `final_prompt` 中的：
```
"【回复纪律】根据球员等级严格执行以下态度：\n"
"- 传奇队长...\n- 核心首发...\n- 一线队...\n- 青训生...\n- 预备队...\n- 看台内鬼...\n"
```

确认这一部分不再出现。

- [ ] **Step 3: 验证语法**

```bash
cd /d/Users/zty/arteta_bot
python -m py_compile plugins/arteta_chat.py && echo "OK"
```

Expected: OK

- [ ] **Step 4: Commit**

```bash
git add plugins/arteta_chat.py
git commit -m "refactor: rewrite ARTETA_PROMPT - remove fixed stories, add opinionated tone, remove 6-level table"
```

---

### Task 5: 用 web-access 技能收集知识库内容（补充丰富）

**Files:**
- Modify: `knowledge_base/` 下各文件

- [ ] **Step 1: 搜索 All or Nothing 纪录片经典语录**

通过 web-access 搜索 "All or Nothing Arsenal Arteta speeches locker room" 补充到 `knowledge_base/documentary/01-locker-room-speeches.md`

- [ ] **Step 2: 搜索阿尔特塔战术分析文章**

搜索 "Arteta inverted fullback tactic"、"Arteta 2-3-5 formation"、"Arteta high press analysis" 补充到 `knowledge_base/tactics/`

- [ ] **Step 3: 搜索阿尔特塔经典发布会语录**

搜索 "Mikel Arteta best press conference quotes"、"Arteta on trust process" 补充到 `knowledge_base/press/01-classic-quotes.md`

- [ ] **Step 4: Commit**

```bash
git add knowledge_base/
git commit -m "feat: enrich knowledge base with web-collected content"
```

---

### Task 6: 部署到服务器

**Files:**
- `plugins/arteta_chat.py`
- `plugins/arteta_tools.py`
- `plugins/arteta_knowledge.py`
- `knowledge_base/`

- [ ] **Step 1: SCP 上传修改和新文件到服务器**

```bash
# 上传修改的主文件
ssh arteta@118.178.140.171 "mkdir -p /opt/arteta_bot/knowledge_base/documentary"
ssh arteta@118.178.140.171 "mkdir -p /opt/arteta_bot/knowledge_base/tactics"
ssh arteta@118.178.140.171 "mkdir -p /opt/arteta_bot/knowledge_base/press"
ssh arteta@118.178.140.171 "mkdir -p /opt/arteta_bot/knowledge_base/philosophy"

scp plugins/arteta_chat.py arteta@118.178.140.171:/opt/arteta_bot/plugins/
scp plugins/arteta_tools.py arteta@118.178.140.171:/opt/arteta_bot/plugins/
scp plugins/arteta_knowledge.py arteta@118.178.140.171:/opt/arteta_bot/plugins/
scp -r knowledge_base/* arteta@118.178.140.171:/opt/arteta_bot/knowledge_base/
```

- [ ] **Step 2: 重启机器人**

```bash
ssh arteta@118.178.140.171 "supervisorctl restart arteta_bot"
```

- [ ] **Step 3: 验证**

```bash
# 检查进程
ssh arteta@118.178.140.171 "supervisorctl status arteta_bot"

# 检查日志（启动后无报错）
ssh arteta@118.178.140.171 "tail -20 /opt/arteta_bot/bot.log"

# 验证知识库文件存在
ssh arteta@118.178.140.171 "ls /opt/arteta_bot/knowledge_base/*/"
```

Expected: 进程运行中，日志无报错，知识库文件存在

- [ ] **Step 4: Commit 部署变更**

```bash
git add plugins/arteta_tools.py plugins/arteta_knowledge.py knowledge_base/
git commit -m "deploy: upload new modules and knowledge base to server"
```
