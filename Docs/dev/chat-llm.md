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
  │  或 on_message 触发（rule=_message_mentions_bot，即 @机器人 / reply 后 @机器人）
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
  │     ├── 最近群聊上下文（daily_messages，含机器人上一轮主回复）
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
at_cmd = on_message(rule=_message_mentions_bot, priority=11, block=True)
```

**指令路由规则**：

- `chat_cmd` (priority=10)：匹配以 `A`/`a`/`塔子`/`阿尔特塔` 开头的消息，调用 `process_chat()`
- `at_cmd` (priority=11)：当消息开头/结尾 `@机器人`，或原始消息中存在 `reply` 后紧跟 `@机器人` 时触发；会跳过以 `A`/`a`/`/` 开头的消息（避免与 chat_cmd 重复处理）
- `algo_cmd` (priority=9)：独立子系统，调用 GPT-5.5 模型处理算法/数学/代码问题，不经过 Function Calling 流程；与 `process_chat` 行为一致——会解析消息中的 `reply` 段或 `event.reply`，调用 `fetch_quoted_chain` 把被引用消息（含其中图片的 vision 识别结果、嵌套引用、合并转发内容）拼成 `【引用消息】：...` 块和当前消息一起喂给 LLM。这覆盖"引用一张题目图片 + `/算法 这道题怎么做`"的常见场景；纯命令无内容也无引用时返回 `把你需要解决的问题写在白板上！`

`at_cmd` 不直接使用 NoneBot 的 `to_me()` 作为 matcher rule，而是使用 `_message_mentions_bot(event)`。原因是 OneBot v11 的 reply 预处理会移除 `reply` 段以及紧随其后的 `at` 段；当用户“回复自己的图片 + @机器人”时，`event.to_me` 不会被置为 `True`，只看处理后的消息会漏触发。自定义规则会同时检查 `event.original_message` 和 `event.get_message()`，覆盖 reply+@ 的图片追问场景，同时避免匹配正文中间随手 @机器人的普通讨论。

### 管理员工具入口

当 `ARTETA_USE_AGENT_REGISTRY=true` 时，主对话会走新 Registry 链路，`plugins/arteta_agent.tools.admin` 中的 `admin_action` 工具会被暴露给模型。管理员可以在正常对话里让 bot 通过 `update_favor` 工具直接修改其他成员的好感度，支持 `favor` 直接设值和 `delta` 增减两种写法。这个工具仍然受 `admin_action` 权限和二次确认保护，执行后会复用 SQLite 好感度等级阈值并写入审计日志，不会绕过安全边界。

### Agent Registry 工具 schema 收窄

`ARTETA_USE_AGENT_REGISTRY=true` 时，`plugins/arteta_agent/planner.py::detect_contextual_tool_exclusions()` 会按当前消息意图和 `ToolContext.extra` 收窄本轮暴露给 LLM 的工具 schema。普通闲聊默认不暴露工具；阿森纳/积分榜/伤病等足球实时意图会开放 `football`、`football_news`、`knowledge` 和 `web` 类工具，让模型优先使用 `grok_search` / `verify_recent_claim` 核实当前信息；链接、文档、图片、渲染、策略、QQ 动作和管理员工具只在对应意图或上下文出现时开放。

工具注册时会校验 OpenAI-compatible 参数 schema 的本地子集：根节点必须是 object，`properties` 必须是对象，`required` 必须是字符串列表，`type` 只能使用 JSON Schema 基础类型，`additionalProperties` 只能是布尔值或对象 schema。坏 schema 会在 `register_tool()` 阶段 fail-fast，不会等到模型请求工具时才暴露。注册通过后，Registry 会把所有 object schema 归一化为默认 `additionalProperties=false`；工具如果确实需要动态键，必须显式写 `additionalProperties=true` 或声明对象 schema，避免模型多传未知参数进入 handler。

`ToolSpec` 还保留三类 runtime 元数据：`parallel_safe` 表示未来是否允许和其他无依赖工具并行执行，`idempotent` 表示重复执行是否不会改变外部状态，`result_contains_untrusted_content` 表示工具结果是否可能包含网页、文档、搜索结果等不可信外部文本。当前这些字段只作为声明式元数据存储在 Registry 中，不会写入 OpenAI-compatible tool schema，也不会让 planner 自动并行执行；默认值保持保守：串行、非幂等、结果视为不可信。

公网实时事实问题还有一层策略化首跳路由：`route.public_current_fact.preferred_tool`。默认值等价于 `grok_search`，可通过 `update_behavior_policy` 或自然语言偏好（如“以后类似这种实事性的问题统一走grok-research”）写入 Behavior Policy。planner 只在识别到公网当前事实且排除“还记得/群里/刚才”等本地记忆语境时使用这条策略；配置的工具不可用时会按 `grok_search`、`verify_recent_claim`、`web_search` 顺序回退。

这个过滤只影响模型“看得见哪些工具”，不承担安全边界。所有写操作、管理员动作、跨群/跨用户访问仍必须经过 `execute_tool_call()` 的参数校验、权限、确认、超时和 trace 记录。强制路由的文档、链接、科学解题、行为策略写入等路径仍可直接执行对应工具，并会在后续总结回答时把已用工具加入 `disabled_tools`，避免模型重复调用。

`confirm_write` 和 `admin_action` 不再接受旧的 `confirmed_tool` 工具名放行。未确认时 executor 会创建 `PendingAction` 并返回 `PendingAction: <id>`；用户需要发送 `确认 <id>`、`确认执行 <id>` 或 `confirm <id>`。planner 只解析这种显式 action id 形式，并把 `confirmed_action_id` 注入 executor。executor 会按 action id、用户、群、工具名和过期时间原子消费 PendingAction，并使用 PendingAction 保存的原始参数执行；用户确认消息或模型后续 tool call 中的新参数会被忽略。`pending_agent_actions.expires_at` 有独立索引，`PendingActionStore.cleanup_expired_actions()` 可按需清理过期记录。

Agent Registry runtime 还有循环保护：默认单次运行最多执行 10 个工具调用，同一工具同一参数最多重复 2 次，累计工具 observation 最多 80000 字符。触发保护时会返回 `[LoopGuard]` 降级文本，停止继续执行工具，避免模型在同一轮里反复调用同一工具、无限扩张上下文或把外部大文本继续塞回 LLM。

executor 内部已使用结构化 `ToolResult` 表示工具状态、权限、参数 key、PendingAction id 和 marker；旧的 `execute_tool_call()` 仍返回字符串以兼容现有工具和测试。planner 的关键控制流应优先看 `ToolResult.status`，不要再把工具正文中的 `[PermissionRequired]` 等文本前缀当作真实权限状态，避免网页/PDF/工具正文伪造控制标记。

executor 还会对安全相关事件写入 `agent_audit_logs`：参数校验失败、未知/禁用工具、权限拒绝、PendingAction 创建、确认失败、确认后执行，以及受保护工具的超时/异常。executor 级审计的 `detail` 是 JSON 字符串，只保存 `event`、`permission`、`arg_keys`、`request_id`、`pending_action_id`、`confirmed_action_id`、`duration_ms`、`error_code` 等元数据；不会保存原始参数值、用户消息正文、异常正文、API key 或工具输出。普通 `safe_read` 成功调用默认不入库，避免把查询结果和网页正文写进审计表。

自主唤醒还有一层 cheap gate：只有“最近/最新/查/总结/链接/文档/图片/积分榜/伤病/新闻”等任务形态才会进入 activation LLM；普通群聊里只是提到“阿森纳/英超”不会触发 activation 请求，单纯 `?` / `？` 也不再作为任务触发条件，避免慢模型网关在无关聊天上产生 `ReadTimeout` 噪声。显式 PendingAction 确认消息（如 `确认 <id>` / `confirm <id>`）会直接进入主 Agent，不经过 activation LLM。

线上如果出现大面积 `ReadTimeout`，优先检查 `ARTETA_USE_AGENT_REGISTRY`、`DEEPSEEK_MODEL`、`DEEPSEEK_API_URL` 和日志里的 `receive_response_headers.failed`。临时止血可以把 `ARTETA_USE_AGENT_REGISTRY=false` 切回 legacy `run_tool_loop()`，但长期应保持 Agent Registry 的 schema 收窄策略，避免普通聊天携带全量工具定义拖慢 BoxYing 响应。

用户画像更新是主回复发送后的后台维护任务。`update_user_profile()` 的 LLM 请求限制为 JSON object 和最多 600 tokens；这类后台请求超时不应阻断主回复，也不应被当作“所有聊天都断联”的根因。

### 文档与链接分析工具

当 `ARTETA_USE_AGENT_REGISTRY=true` 时，主聊天链路会把当前消息和引用消息中的文档、链接收集到 `ToolContext.extra`：

- `image_urls`：图片 URL，供 `analyze_image` 使用。
- `document_urls`：PDF/DOCX 文档引用，供 `read_document` 使用。
- `detected_urls`：消息和引用里的 http/https 链接，供 `analyze_links` 使用。

新增的只读工具：

| 工具 | 权限 | 作用 | 产物 |
|------|------|------|------|
| `read_document` | `safe_read` | 读取当前消息/引用中的 PDF 或 DOCX，也可显式传入文档 URL。DOCX 使用标准库 `zipfile` + XML 解析；PDF 优先使用可选依赖 `pypdf` 或 `PyPDF2`。 | 返回文档名、类型、链接和正文摘录 |
| `analyze_links` | `safe_read` | 自动检测当前消息/引用里的链接，抓取标题、发布时间和正文摘录，并优先用 Playwright 截取网页可视区域截图。 | 保存 JSON 内容快照和 PNG 网页截图到 `artifacts/agent_tools/link_snapshots/`，并在工具结果中返回截图 artifact |

入口约束：

- 只接受 `http/https` URL，不读取本地任意路径。
- 文档工具只支持 `.pdf` / `.docx` 或对应 Content-Type，其他格式会拒绝。
- 用户引用文档并提问时，prompt 原则要求模型调用 `read_document`，不要假装读过。
- 用户要求“看看链接/总结链接/截取快照/这篇讲什么”时，prompt 原则要求模型调用 `analyze_links`。

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

### 最近群聊上下文

在 ChromaDB 语义检索之外，主聊天链路还会读取 SQLite `daily_messages` 表中的本群最近消息，作为短期时间线注入到 system prompt。它解决的是 ChromaDB 不稳定适合处理的“短距离指代”和“连续对话”问题，例如用户问“那刚刚你说的第二步呢”时，模型应该能看到机器人上一轮已经回复过什么。

读取和注入流程：

```text
get_recent_group_messages(group_id)
  -> SELECT ... FROM daily_messages WHERE group_id = ? ORDER BY timestamp DESC LIMIT ?
  -> format_recent_group_context(rows)
  -> append_recent_group_context(messages, rows)
```

写入来源有两个：

- 用户群消息：`plugins/arteta_daily.py::record_message()` 在群消息非空时写入 `daily_messages`。
- 机器人主回复：`plugins/arteta_chat.py::save_bot_reply_to_daily_messages()` 在主回复图片成功发送后写入 `daily_messages`。

机器人回复写入有几条约束：

- 使用 `context_answer`，它在 trace/debug footer 拼接前截取，因此下一轮 LLM 不会把测试 trace 当成真实对话。
- 写入前通过 `_strip_context_style_tags()` 清理 `[red]`、`[bold]`、`[color=#...]`、`[font size=...]` 等渲染标签，只保留自然语言内容。
- 写入失败不影响对话发送，只打印 `[RecentContext] save bot reply failed group=...`。
- `daily_messages` 读取必须始终限制当前 `group_id`，避免跨群上下文泄露。
- 最近上下文只用于理解指代和事实，不作为回复风格模板；主链路会在全部上下文注入后调用 `append_current_turn_style_guard()`，把“第一句就要有劲、语气要有起伏”的本轮风格约束放到 system prompt 末尾。

最近群聊上下文和 ChromaDB 记忆的分工：

| 机制 | 作用 |
|------|------|
| `daily_messages` 最近窗口 | 当前群最近时间线，适合连续聊天、短距离指代、看见机器人上一轮主回复 |
| ChromaDB `group_memories` | 长期语义回忆，适合跨天、跨主题、非连续但语义相关的历史问答 |

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
3. **空最终回复重试**：如果 LLM 没有 `tool_calls` 但 `content` 为空，会追加一条用户消息 `请直接给出最终回复，不要返回空内容。` 并继续下一轮，避免上层收到空字符串
4. **超过 5 轮强制退出**：返回最后一条消息的内容

### call_deepseek_tool

```python
async def call_deepseek_tool(messages: List[dict]) -> List[dict]:
```

- 使用 httpx.AsyncClient 调用 BoxYing API (`https://www.boxying.com/v1/chat/completions`)
- 模型：`gpt-5.5`
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

真正触发 90s 超时时，用户会收到 `⏰ 教练这次思考太久，重新说一遍？`。如果用户收到 `让我想想再回答你。`，说明 `run_tool_loop()` 返回了空答案，而不是超时；当前实现会先在工具循环内对空 `content` 做一次继续追问，仍为空时才进入这个兜底分支。

### 回归测试

相关行为由以下测试覆盖：

- `tests/test_arteta_chat_vision.py`：覆盖 Vision 请求格式、响应解析，以及 reply+@ 触发规则
- `tests/test_arteta_tools.py`：覆盖 DeepSeek 最终回复 `content` 为空时的重试
- `tests/test_arteta_football_news.py`：覆盖图片理解问题不会被足球新闻直答逻辑误拦截

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
| `DEEPSEEK_TEMPERATURE` | 主对话生成温度，默认 `0.9`；画像分析仍固定 `0.3`，激活判定仍固定 `0` | float |
| `FOOTBALL_API_TOKEN` | football-data.org API Token | string |
| `ARSENAL_ID` | 阿森纳在 football-data.org 的 ID（固定 57） | int |

### 工具模块配置（arteta_tools.py）

工具模块通过 `register_config()` 函数在 bot 启动时注入全局配置：

```python
register_tools_config(
    football_api_token=FOOTBALL_API_TOKEN,
    deepseek_api_key=DEEPSEEK_API_KEY,
    deepseek_temperature=DEEPSEEK_TEMPERATURE,
    arsenal_id=ARSENAL_ID,
    has_web_search=HAS_WEB_SEARCH,
)
```

### API 端点

| 用途 | 端点 | 模型 |
|------|------|------|
| 主对话 + Function Calling | `https://www.boxying.com/v1/chat/completions` | `gpt-5.5` |
| 算法/技术问题 | `https://www.boxying.com/v1/chat/completions` | `gpt-5.5` |
| 人格画像分析 | `https://www.boxying.com/v1/chat/completions` | `gpt-5.5` |

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
