# Arteta Bot 架构概览

> 开发者入口文档 — 帮助你快速理解项目结构与数据流。

---

## 1. 项目定位

基于 **NoneBot2 + OneBot V11 (NapCat)** 的 QQ 群聊机器人，模拟阿森纳主教练米克尔-阿尔特塔（Mikel Arteta）的角色身份，与群成员进行角色扮演式对话，并提供足球数据查询、AI 图片生成、每日总结、周报等附加功能。

相关开发文档：

- [开发者功能验证](developer-verification.md) — 本地回归脚本、suite 划分、输出报告说明

---

## 2. 技术栈

| 类别 | 技术 | 用途 |
|------|------|------|
| 框架 | NoneBot2 | 事件驱动机器人框架 |
| 协议适配 | OneBot V11 (NapCat QQ) | QQ 消息协议适配 |
| LLM | DeepSeek API (`deepseek-v4-flash`) | AI 对话、Function Calling、周报生成 |
| 关系数据库 | SQLite / aiosqlite | 用户数据、发言记录、好感度等结构化数据 |
| 向量数据库 | ChromaDB (PersistentClient) | 语义化群聊记忆存储与检索 |
| HTML 渲染 | Playwright + Jinja2 + KaTeX + marked.js | 将 Markdown/LaTeX 渲染为图片输出 |
| 图片回退渲染 | Pillow + Pilmoji | 纯文本场景无需启动浏览器 |
| 图表 | matplotlib | 好感度条形图 |
| 足球数据 | football-data.org API | 比赛结果、积分榜、伤病信息 |
| 新闻搜索 | DuckDuckGo Search (`duckduckgo_search`) | 足球/转会新闻搜索 |
| 图片生成 | gpt-image-2 API (via SiliconFlow / BoxYing) | AI 文生图 |
| 图片识别 | Vision API (gpt-4o-mini / Qwen3-VL) | 识别用户发送的图片内容 |
| 定时任务 | APScheduler (nonebot_plugin_apscheduler) | 每日总结、每周周报定时触发 |
| 日志 | loguru | 全日志系统（替代标准 logging） |

---

## 3. 文件职责

### 启动入口

| 文件 | 职责 |
|------|------|
| `bot.py` | 启动入口；初始化 loguru 日志系统（文件轮转 + 终端彩色输出）；注册 OneBot V11 Adapter；扫描并加载 `plugins/` 下所有插件 |

### 核心插件

| 文件 | 职责 |
|------|------|
| `plugins/arteta_chat.py` | **AI 对话核心**。包含：指令定义 (`A`/`塔子`/`阿尔特塔`、`算法`、`盒` 等)、`process_chat()` 主流程、好感度系统 (`extract_favor_marker`, `check_keyword_penalty`, `apply_favor_change`)、数据库初始化、成员追踪、图片视觉识别 |
| `plugins/arteta_tools.py` | **Function Calling 工具注册与执行器**。定义 7 个工具（比赛结果、积分榜、伤病、新闻搜索、知识库查询、群成员列表、成员关系）；`run_tool_loop()` 驱动多轮工具调用 |
| `plugins/arteta_memory.py` | **ChromaDB 向量记忆**。`MemoryStore` 全局单例：`add_memory()` 存入、`query_memory()` 语义检索；集合名 `group_memories` |
| `plugins/arteta_render.py` | **图片渲染引擎**。PIL/Pilmoji 文字排版 (`text_to_tactical_board`)；Playwright HTML→图片 (`html_to_image`, `needs_html_render`)；matplotlib 好感度条形图 (`favorability_bar_chart`) |

### 功能插件

| 文件 | 职责 |
|------|------|
| `plugins/arteta_knowledge.py` | **本地知识库检索引擎**。加载 `knowledge_base/` 下所有 `.md` 文件到缓存，按关键词检索 |
| `plugins/arteta_admin.py` | **管理员/禁言功能**。`下放/禁言/红牌` 指令：禁言目标成员 + 扣除 10 点好感度 |
| `plugins/arteta_cmath.py` | **理科解题渲染**。`算法/数学/物理/leetcode` 等指令；调用 DeepSeek API 并渲染为 LaTeX 图片（matplotlib usetex）；已被 `算法` 指令覆盖 |
| `plugins/arteta_daily.py` | **每日群聊总结**。记录所有群消息到 `daily_messages` 表；APScheduler 每天 22:30 自动生成并发布总结；`/今日总结` 手动触发 |
| `plugins/arteta_weekly.py` | **阿森纳周报**。爬取 BBC/Sky Sports 新闻；LLM 摘要生成；注入知识库；周一自动群发；`/周报` 手动触发 |
| `plugins/arteta_image.py` | **AI 图片生成**。`画图` 指令：调用 gpt-image-2 API 生成图片并发送 |
| `plugins/arteta_help.py` | **帮助菜单**。`帮助/help/menu` 指令：输出战术指令板（图片格式） |
| `plugins/arteta_like.py` | **QQ 名片赞**。`赞我/点赞我` 指令：调用 QQ 名片赞 API，每日限额 |
| `plugins/arteta_standings.py` | **英超积分榜**。`英超局势/积分榜/排名` 指令：从 football-data.org 获取数据，LLM 分析后渲染 |
| `plugins/arteta_swear.py` | **誓言系统**。`发誓/立帖为证` 指令：记录用户目标至 JSON 文件；`我的誓言` 查看 |

### 目录结构

| 目录 | 用途 |
|------|------|
| `knowledge_base/` | 本地知识库，存放 `.md` 格式的阿尔特塔语录、战术文档、球员信息等 |
| `templates/` | HTML 渲染模板，`arteta_render.html` 为 Playwright 渲染提供 Jinja2 模板 |
| `deploy/` | 部署脚本：Docker 构建 (`Dockerfile`, `docker-compose.yml`)、ECS 部署 (`deploy_ecs.sh`)、远程部署 (`deploy_remote.py`, `deploy_quick.py`) |
| `logs/` | 运行时日志，自动轮转（10MB, 保留 5 个） |
| `chroma_db/` | ChromaDB 持久化数据目录 |
| `data/` | 运行时数据（誓言 JSON 等） |
| `Docs/` | 项目文档 |

---

## 4. 数据流 — 对话处理流程

用户发送消息后，经过以下流水线处理：

```
用户输入
    │
    ▼
on_message / on_command 触发
    │  (rule=to_me() 或 "A/塔子" 等前缀)
    │
    ▼
process_chat(bot, event, custom_prompt)
    │
    ├── 1. 获取用户数据
    │   └── get_player_data(user_id, group_id)
    │       ├── 从 players 表加载 (level, favorability, profile_json)
    │       └── 从 nicknames 表加载昵称历史
    │
    ├── 2. 构建 base_prompt（系统提示词）
    │   ├── 角色设定（阿尔特塔身份）
    │   ├── 更衣室概况（群成员列表与好感度）
    │   ├── 用户画像（profile_json + 历史互动）
    │   └── 历史相关记忆
    │       └── memory_store.query_memory(group_id, user_message, n_results=5)
    │
    ├── 3. run_tool_loop(messages)
    │   ├── 最多 5 轮 Function Calling 循环
    │   ├── 每轮：call_deepseek_tool() → 解析 tool_calls
    │   ├── 执行工具 → 结果追加到 messages
    │   └── 工具列表（7 个，详见 arteta_tools.py）
    │
    ├── 4. LLM 最终回复
    │   └── 不含工具调用的纯文本回复
    │
    ├── 5. 好感度更新
    │   ├── extract_favor_marker(answer) → 解析 [+1]/[-1]/[+3] 等标记
    │   ├── check_keyword_penalty(prompt) → 关键词辅助扣分
    │   └── apply_favor_change(user_id, group_id, nickname, inc)
    │       └── 更新 players 表 favorability/level
    │
    ├── 6. 存入 ChromaDB
    │   └── memory_store.add_memory(group_id, user_id, user_message, answer)
    │
    └── 7. 渲染输出
        ├── needs_html_render(text) → True: html_to_image(text)
        │   └── Playwright Chromium → Jinja2 模板 → KaTeX/marked → 截图
        └── False: text_to_tactical_board(text)
            └── PIL + Pilmoji → 战术板风格图片
```

### 好感度系统

好感度 (favorability) 是群成员与"阿尔特塔"之间关系的量化指标：

- **等级体系**：青训生 (默认) → 轮换球员 → 主力 → 核心球员 → 传奇
- **好感度增减**：
  - AI 在回复末尾插入标记 `[+N]` 或 `[-N]`（N=1~3），由 `extract_favor_marker()` 解析
  - `check_keyword_penalty()` 对负面关键词（如摆烂、开摆）自动扣分
  - 管理员操作不受好感度影响
- **应用**：`apply_favor_change()` 更新 `players` 表，并根据新好感度自动调整等级

### 渲染路由

- `needs_html_render()` 检测文本是否包含复杂元素（Markdown 表格、代码块、LaTeX 公式）
- **HTML 路径**：Jinja2 渲染模板 → Playwright 加载 → KaTeX 渲染公式 → marked 转 Markdown → 截图返回 bytes
- **PIL 路径**：Pilmoji 排版 + Pillow 绘制战术板风格图片，适合纯文本场景

---

## 5. 数据库表概览

### SQLite — `arsenal_data.db`

| 表名 | 用途 | 主要字段 | 所在文件 |
|------|------|---------|---------|
| `players` | 用户数据，主表 | `user_id, group_id, nickname, level, favorability, last_seen, profile_json` | arteta_chat.py |
| `nicknames` | 昵称变更历史 | `user_id, group_id, nickname, first_seen, last_seen` | arteta_chat.py |
| `messages` | 发言记录 | `user_id, group_id, message, timestamp` | arteta_chat.py |
| `profile_updates` | 人格画像更新日志 | `user_id, group_id, old_profile, new_profile, trigger_message, timestamp` | arteta_chat.py |
| `member_relations` | 成员互动关系 | `user_id, target_user_id, group_id, interaction_count, last_interaction_time` | arteta_chat.py |
| `daily_likes` | 每日点赞次数计数 | `user_id, like_date, count` (联合主键) | arteta_like.py |
| `daily_messages` | 每日消息记录（总结用） | `id, user_id, group_id, nickname, message, timestamp` | arteta_daily.py |

### ChromaDB — `chroma_db/` 目录

| Collection | 用途 | 管理位置 |
|------------|------|---------|
| `group_memories` | 语义向量记忆：每条记录包含用户消息 + AI 回复 + 群号/用户 ID metadata | arteta_memory.py |

### JSON 文件

| 文件 | 用途 | 管理位置 |
|------|------|---------|
| `data/arteta_swears.json` | 誓言持久化存储 | arteta_swear.py |

---

## 6. Function Calling 工具

`arteta_tools.py` 定义了 7 个工具，供 LLM 在对话中按需调用：

| 工具名 | 功能 | 数据源 |
|--------|------|--------|
| `get_arsenal_result` | 获取阿森纳最近比赛结果 | football-data.org API |
| `get_pl_table` | 获取英超积分榜 | football-data.org API |
| `get_arsenal_injuries` | 获取阿森纳伤病名单 | football-data.org API |
| `search_news` | 搜索足球/转会新闻 | DuckDuckGo Search |
| `get_football_knowledge` | 查询本地知识库 | `knowledge_base/` .md 文件 |
| `get_group_members` | 获取群内活跃成员列表 | SQLite players 表 |
| `get_member_relations` | 查询成员互动关系 | SQLite member_relations 表 |

工具调用流程：
1. LLM 返回 `tool_calls` 数组
2. `execute_tool_call()` 分发到对应实现函数
3. 结果以字符串形式追加到 messages
4. 重新请求 LLM，最多重复 5 轮
5. 若无工具调用则返回最终回复

---

## 7. 环境变量

配置以 NoneBot2 的 `.env` / `.env.dev` / `.env.prod` 方式加载，通过 `driver.config` 访问。

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `ENVIRONMENT` | 环境标识 (`dev`/`prod`) | `dev` |
| `SUPERUSERS` | 管理员 QQ 号列表（JSON 数组） | `["2648955710"]` |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | — |
| `ZHIPU_API_KEY` | 备用 API 密钥（暂无实际使用） | — |
| `FOOTBALL_API_TOKEN` | football-data.org API Token | `da24063a4040404c89250b601f8994a2` |
| `IMAGE_API_KEY` | 图片生成 API 密钥 | — |
| `IMAGE_API_URL` | 图片生成 API 地址 | `https://www.boxying.com` |
| `IMAGE_MODEL` | 图片生成模型 | `gpt-image-2` |
| `VISION_MODEL` | 图片识别模型 | `gpt-4o-mini` |
| `HOST` | 监听地址 | `0.0.0.0` |
| `PORT` | 监听端口 | `8088` |
| `COMMAND_START` | 指令前缀 | `["", "/"]` |

---

## 8. 定时任务

由 `nonebot_plugin_apscheduler` 管理：

| 任务 | 触发时间 | 所在文件 |
|------|---------|---------|
| 每日群聊总结 | 每天 22:30 | arteta_daily.py |
| 阿森纳周报 | 每周一 10:00 | arteta_weekly.py |
| 每日消息清理 | 每天 03:00 (清理 7 天前数据) | arteta_daily.py |

---

## 9. 部署

部署脚本位于 `deploy/` 目录：

- `Dockerfile` + `docker-compose.yml` — Docker 容器化部署
- `deploy_docker.sh` — Docker 一键部署脚本
- `deploy_ecs.sh` — 阿里云 ECS 部署脚本
- `deploy_remote.py` — 远程部署 Python 脚本
- `deploy_quick.py` — 快速部署脚本

生产环境日志路径：`/opt/arteta_bot/logs/`
开发环境日志路径：`./logs/`

---

## 10. 知识库结构

本地知识库目录 `knowledge_base/` 包含按主题分类的 `.md` 文件：

```
knowledge_base/
├── arsenal_knowledge_base.md    # 综合知识库（球员、历史、战术）
├── glossary.md                  # 战术术语表
├── tactics/                     # 战术文档
├── philosophy/                  # 足球哲学
├── press/                       # 发布会语录
├── documentary/                 # 纪录片相关内容
└── ...
```

`arteta_knowledge.py` 在首次查询时将全部文件加载到内存缓存，按关键词进行文本匹配检索。`/刷新情报` 指令可清除缓存，强制重新加载。

---

> 本文档面向开发者。如有疏漏或与最新代码不一致之处，请以源码为准。
