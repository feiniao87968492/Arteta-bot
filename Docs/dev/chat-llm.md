# AI 对话系统与 LLM 集成

> 本文档详细说明 Arteta Bot 的 AI 对话系统架构、LLM 集成方式以及 Function Calling 实现细节。
> 阅读前建议先了解 [overview.md](overview.md) 中的整体架构。

---

## 1. 背景

在早期版本中，机器人在每次对话响应前都会被动地**预先拉取**阿森纳比赛数据和英超积分榜，并将这些信息强行注入到每次对话的 prompt 中。这种做法存在两个问题：

1. **浪费 Token**：用户可能只是打招呼或闲聊，不需要实时数据
2. **缺乏灵活性**：LLM 只能被动接收数据，无法自主决定需要什么信息

当前系统采用 **DeepSeek Function Calling** 方案，将数据获取的决策权交给 LLM。LLM 根据用户意图自主决定调用哪些工具（查比分、查排名、搜新闻、查知识库等），使得对话更加自然、高效。

---

## 2. 架构总览

AI 对话的核心流程如下：

```
用户输入
  │
  ▼
on_command 触发（匹配 "A"/"塔子"/"阿尔特塔" 前缀）
  │  或 on_message 触发（rule=to_me()，即 @机器人）
  │
  ▼
process_chat(bot, event, custom_prompt)
  │
  ├── 1. get_player_data() 获取用户数据
  │     ├── 当前等级（level）
  │     └── 当前好感度（favorability）
  │
  ├── 2. 提取引用消息链（递归，最多 3 层）
  │
  ├── 3. 分析用户发送的图片（如有）
  │
  ├── 4. 构建 base_prompt
  │     ├── ARTETA_PROMPT（角色设定）
  │     ├── 当前时间、群号
  │     ├── 引用消息链 + 图片分析结果
  │     ├── 用户个人信息（昵称、等级、好感度）
  │     ├── 当前一线队阵容
  │     ├── 用户人格画像（profile_json）
  │     ├── 更衣室概况（活跃成员快照）
  │     └── ChromaDB 相关历史记忆
  │
  ├── 5. run_tool_loop(messages)
  │     ├── 最多 5 轮 Function Calling 循环
  │     ├── 每轮：call_deepseek_tool() → 解析 tool_calls
  │     ├── 执行工具 → 结果追加到 messages
  │     └── 直到 LLM 返回纯文本回复
  │
  ├── 6. LLM 回复后处理
  │     ├── extract_favor_marker() 提取好感度标记
  │     ├── check_keyword_penalty() 关键词辅助扣分
  │     ├── apply_favor_change() 更新好感度和等级
  │     ├── memory_store.add_memory() 存入 ChromaDB
  │     └── 触发人格画像更新（条件判断）
  │
  └── 7. 渲染输出
        ├── needs_html_render() → True: html_to_image()
        └── False: text_to_tactical_board()
```

**关键特点**：

- `process_chat()` 本身**不阻塞**：它通过 `asyncio.create_task(delayed_response())` 将 LLM 调用放入后台任务，主协程立即返回
- 好感度更新和画像更新都在 LLM 返回后进行，不影响对话响应速度
- 回复始终以图片形式发送（战术板风格或 HTML 渲染）

---

## 3. 指令注册

AI 对话相关的指令在 `plugins/arteta_chat.py` 顶部定义：

```python
# 核心 AI 对话指令
chat_cmd = on_command("A", aliases={"a", "塔子", "阿尔特塔"}, priority=10, block=True)

# 算法/技术问题指令（调用 GPT-5.5，独立于主对话系统）
algo_cmd = on_command("算法", aliases={"代码", "leetcode", "战术演练", "算法题",
                                       "amath", "物理", "数学", "计算"}, priority=9, block=True)

# 其他数据查询指令
box_cmd    = on_command("盒", priority=8, block=True)                    # 查看球员档案
fav_cmd    = on_command("好感度", priority=5, block=True)                 # 查看自己的好感度
rank_cmd   = on_command("好感度排行", aliases={"排行", "ranking", "信任度排行"}, priority=5, block=True)
profile_cmd= on_command("档案", aliases={"profile", "个人档案"}, priority=6, block=True)  # 个人详细档案
refresh_cmd= on_command("刷新情报", priority=4, block=True)               # 清除缓存强制刷新

# @机器人触发（无前缀的被动唤醒）
at_cmd = on_message(rule=to_me(), priority=11, block=True)
```

**指令路由规则**：

- `chat_cmd` (priority=10)：匹配以 `A`/`a`/`塔子`/`阿尔特塔` 开头的消息，调用 `process_chat()`
- `at_cmd` (priority=11)：当 `@机器人` 时触发，但会跳过以 `A`/`a`/`/` 开头的消息（避免与 chat_cmd 重复处理）
- `algo_cmd` (priority=9)：独立子系统，调用 GPT-5.5 模型处理算法/数学/代码问题，不经过 Function Calling 流程

---

## 4. ARTETA_PROMPT

系统提示词（System Prompt）定义在 `arteta_chat.py` 的 `ARTETA_PROMPT` 常量中，是整个对话系统的"灵魂"。关键组成部分如下：

### 角色设定

> "你是阿森纳主帅米克尔·阿尔特塔。"

### 性格与执教哲学

1. **热爱球员**：欣赏拼搏精神和能量，热情回应每一个问题
2. **观点鲜明**：不说"端水"的话，该表扬表扬，该批评批评
3. **了解每个球员**：根据球员性格、说话风格、支持球队调整回应方式
4. **丰富的足球知识**：引用战术理念解释问题，但要用在更衣室里讲话的方式
5. **利用工具了解更衣室**：使用 `get_group_members` 和 `get_member_relations` 获取群内信息

### 回复原则（最重要的 3 条）

- **观点鲜明**：球员来找你是想听真实看法
- **简短有力**：不要堆数据、不要列清单，用短句、分段、感叹号表达态度
- **不要反复讲故事**：经典故事（灯泡演讲、大脑心脏演讲）用一次就够了

### 回答纪律

1. **正面回答所有问题**，不准回避
2. 如有**引用消息链**，逐条评价每条引用消息
3. **好感度标记**（死命令）：回复正文结束后另起一行，输出且只输出一个好感度标记
4. **数学公式**：行内用 `$...$`，独立公式用 `$$...$$`
5. **代码**：用 ` ``` ` 包裹

### 好感度标记系统

LLM 必须在每次回复末尾输出以下七种标记之一：

| 标记 | 含义 | 好感度变化范围 |
|------|------|---------------|
| `【好感度+++】` | 表现令人惊叹，极大提升了信任 | +380 ~ +770 |
| `【好感度++】` | 表现出色，大幅提升了信任 | +200 ~ +370 |
| `【好感度+】` | 表现积极，提升了信任 | +10 ~ +190 |
| `【好感度=】` | 表现平淡，信任度无变化 | 0 |
| `【好感度-】` | 表现欠佳，降低了信任 | -190 ~ -10 |
| `【好感度--】` | 表现恶劣，大幅降低了信任 | -370 ~ -200 |
| `【好感度---】` | 行为极端恶劣，信任度严重受损 | -770 ~ -380 |

---

## 5. base_prompt 动态注入

在 `process_chat()` 中，除了 `ARTETA_PROMPT` 外，还会动态构建以下上下文信息拼接到 system message 中：

### 更衣室概况

通过 `get_active_members_snapshot(group_id)` 获取近 24 小时活跃的球员列表（最多 8 人），包含昵称、等级图标和好感度：

```
○ 小明(好感85)、● 小红(好感230)、★ 小刚(好感520)
```

等级图标映射：传奇队长=★、核心首发=◆、一线队=●、青训生=○、预备队=△、看台内鬼=▼

### 用户画像

通过 `get_profile_section(user_id, group_id)` 从 `players` 表的 `profile_json` 字段获取。画像由独立的 LLM 分析流程（`update_user_profile()`）定期更新，包含以下维度：

- 真实姓名（real_name）
- 外号/别名（nicknames，列表形式）
- 性格特征（personality）
- 兴趣爱好（interests）
- 支持球队（favorite_team）
- 讨厌球队（rival_teams）
- 说话风格（speaking_style）
- 背景信息（background）
- 与阿尔特塔的关系（relationship_with_arteta）
- 值得记住的事件（notable_events）

### 当前一线队阵容

从 `knowledge_base/arsenal_knowledge_base.md` 中提取球员名单部分，确保 LLM 使用最新阵容信息而非训练数据中的旧名单。

### 相关历史记忆

通过 ChromaDB 的 `memory_store.query_memories(group_id, user_message)` 按语义检索本群相关历史对话，返回最多 5 条匹配记录，格式化为：

```
--- 05月10日 ---
User: 昨天比赛看了吗？
Assistant: 当然看了，球员们的能量令人惊叹...
```

---

## 6. Function Calling 系统

定义在 `plugins/arteta_tools.py` 中，包含 7 个注册工具和一个多轮调用循环。

### 工具列表

| 工具名称 | 功能描述 | 数据来源 | 参数 |
|---------|---------|---------|------|
| `get_arsenal_result()` | 获取阿森纳最近比赛结果（比分、对手、赛事） | football-data.org API | 无 |
| `get_pl_table()` | 获取英超积分榜（前几名、后几名、阿森纳位置） | football-data.org API | 无 |
| `get_arsenal_injuries()` | 搜索阿森纳最新伤病信息 | DuckDuckGo Search | 无 |
| `search_news(q)` | 搜索足球/转会相关最新新闻（搜索词用英文） | DuckDuckGo Search | `q`: 搜索关键词 |
| `get_football_knowledge(topic)` | 查询阿尔特塔知识库（战术概念、更衣室故事、发布会语录等） | `knowledge_base/` .md 文件 | `topic`: 查询主题 |
| `get_group_members(group_id)` | 获取群内活跃球员名单（近 24h 有发言的） | SQLite players + messages 表 | `group_id`: 群号 |
| `get_member_relations(group_id, user_id)` | 查询某位球员的社交互动关系 | SQLite member_relations 表 | `group_id`: 群号, `user_id`: QQ号 |

### 工具定义格式

所有工具使用 OpenAI/DeepSeek 兼容的 Function Calling 格式定义在 `TOOLS` 列表中。例如：

```python
{
    "type": "function",
    "function": {
        "name": "search_news",
        "description": "搜索足球/转会/阿森纳相关最新新闻...",
        "parameters": {
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "英文搜索关键词..."
                }
            },
            "required": ["q"]
        }
    }
}
```

### 工具调用循环 (`run_tool_loop`)

```python
async def run_tool_loop(user_messages: List[dict]) -> str:
```

流程如下：

1. **初始化**：复制 user_messages（包含 system prompt + user message）
2. **循环（最多 5 轮）**：
   - 调用 `call_deepseek_tool(messages)` 发送完整消息列表 + 工具定义
   - 检查响应是否包含 `tool_calls`
   - 如果不包含 → LLM 返回了最终回复，循环结束
   - 如果包含 → 对每个 `tool_call` 调用 `execute_tool_call()`
   - 将执行结果以 `{"role": "tool", "tool_call_id": "...", "content": "..."}` 格式追加回 messages
   - 进入下一轮
3. **超过 5 轮强制退出**：返回最后一条消息的内容

### call_deepseek_tool

```python
async def call_deepseek_tool(messages: List[dict]) -> List[dict]:
```

- 使用 httpx.AsyncClient 调用 DeepSeek API (`https://api.deepseek.com/v1/chat/completions`)
- 模型：`deepseek-v4-flash`
- timeout：80s（单次请求）
- 返回包含 role/content/tool_calls/reasoning_content 的消息字典列表

### execute_tool_call

```python
async def execute_tool_call(tc: dict) -> str:
```

根据 `tc["function"]["name"]` 分发到具体实现函数，返回纯文本结果。其中两个工具依赖 SQLite 查询，两个工具依赖 football-data.org API，两个工具依赖 DuckDuckGo 搜索，一个工具依赖本地知识库。

---

## 7. 边界情况与注意事项

### reasoning_content 保留

DeepSeek 的"思考模式"会在 API 响应中返回 `reasoning_content` 字段。在 Function Calling 多轮循环中，这个字段**必须原样传回**给下一次请求，否则会丢失思考链信息：

```python
# call_deepseek_tool() 中：
if "reasoning_content" in msg and msg["reasoning_content"]:
    result_messages[0]["reasoning_content"] = msg["reasoning_content"]
```

### FinishedException 不应该被通用 except 捕获

NoneBot 使用 `FinishedException` 来中断指令处理（例如 `cmd.finish()` 会抛出此异常）。在 `algo_cmd` 的处理中有一处显式的处理模式：

```python
except FinishedException:
    raise   # 重新抛出，不让通用 except 吞掉
except Exception as e:
    await algo_cmd.finish(Message(f"回复处理出错：{str(e)}"))
```

这是一个曾经出现过的 bug：如果通用 `except Exception` 在前，会捕获并吞掉 `FinishedException`，导致指令无法正常终止。

### 异步超时处理

LLM 调用可能耗时较长（Function Calling 多轮加上外部 API 延迟）。系统使用 `asyncio.create_task()` 将 LLM 调用放入后台任务，确保主协程不被阻塞：

```python
# process_chat() 最后：
asyncio.create_task(delayed_response())
```

后台任务内有 90s 超时保护：

```python
answer = await asyncio.wait_for(run_tool_loop(messages), timeout=90.0)
```

### WebSocket 心跳

将 LLM 调用放入后台任务的另一个原因是避免阻塞 NoneBot 的 WebSocket 心跳处理。如果主协程长时间阻塞，QQ 服务器会认为机器人离线。`asyncio.create_task` 确保 `process_chat()` 立即返回，NoneBot 可以继续处理新的消息和心跳。

### 关键词辅助扣分

在 LLM 好感度评估的基础上，系统还通过 `check_keyword_penalty()` 对用户的发言进行关键词检测。分为三个等级：

- **重度负面词**（如辱骂、恶意攻击）：-80 ~ -40
- **中度负面词**（如下课、垃圾、菜鸡）：-40 ~ -15
- **轻度负面词**（如无聊、失望、摆烂）：-20 ~ -5

这是对 LLM 评估的补充——因为 LLM 可能对某些明显的负面言辞放水。

### 管理员模式

管理员（ADMIN_QQ = "2648955710"）的账号固定为"传奇队长"等级、好感度 999999，不参与好感度计算，也不受关键词扣分影响。这是为了避免管理员测试时频繁产生好感度变动。

---

## 8. 配置项

AI 对话相关的配置通过 NoneBot 的 `.env` 文件加载，通过 `driver.config` 访问：

### 主配置（arteta_chat.py）

| 变量 | 说明 | 类型 |
|------|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | string |
| `FOOTBALL_API_TOKEN` | football-data.org API Token | string |
| `ARSENAL_ID` | 阿森纳在 football-data.org 的 ID（固定 57） | int |

### 工具模块配置（arteta_tools.py）

工具模块通过 `register_config()` 函数在 bot 启动时注入全局配置：

```python
register_tools_config(
    football_api_token=FOOTBALL_API_TOKEN,
    deepseek_api_key=DEEPSEEK_API_KEY,
    arsenal_id=ARSENAL_ID,
    has_web_search=HAS_WEB_SEARCH,
)
```

### API 端点

| 用途 | 端点 | 模型 |
|------|------|------|
| 主对话 + Function Calling | `https://api.deepseek.com/v1/chat/completions` | `deepseek-v4-flash` |
| 算法/技术问题 | `https://www.boxying.com/v1/chat/completions` | `gpt-5.5` |
| 人格画像分析 | `https://api.deepseek.com/v1/chat/completions` | `deepseek-v4-flash` |

### 其他相关配置

| 变量 | 说明 | 所在模块 |
|------|------|---------|
| `HAS_WEB_SEARCH` | 是否安装了 `duckduckgo_search` 库 | arteta_tools.py |
| `CHROMA_DB_DIR` | ChromaDB 持久化目录（默认 `./chroma_db/`） | arteta_memory.py |
| `N_RESULTS` | 每次语义检索返回条数（5） | arteta_memory.py |
| `DB_PATH` | SQLite 数据库路径（`arsenal_data.db`） | arteta_chat.py / arteta_tools.py |

---

## 9. 关联文件速查

| 文件 | 与本系统的关系 |
|------|--------------|
| `plugins/arteta_chat.py` | 对话主流程、指令注册、ARTETA_PROMPT、好感度系统、画像系统 |
| `plugins/arteta_tools.py` | 7 个 Function Calling 工具定义、`run_tool_loop()` 循环、工具实现 |
| `plugins/arteta_memory.py` | ChromaDB 记忆存储与检索，`MemoryStore` 全局单例 |
| `plugins/arteta_knowledge.py` | 本地知识库检索引擎，被 `get_football_knowledge` 工具调用 |
| `plugins/arteta_render.py` | 图文渲染引擎，将 LLM 回复转为图片 |
| `knowledge_base/` | 本地知识库目录，包含战术、哲学、语录等 |

---

> 本文档基于源码 `plugins/arteta_chat.py`、`plugins/arteta_tools.py`、`plugins/arteta_memory.py` 编写。
> 如有与最新代码不一致之处，请以源码为准。
