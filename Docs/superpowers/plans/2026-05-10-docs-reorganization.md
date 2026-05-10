# Docs 目录重组实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建 `Docs/` 目录，将 `PROGRESS.md` 按功能重写为独立文档，补充运维文档

**Approach:** 先建目录结构归档旧文件，然后从 `PROGRESS.md` 提取素材按功能重写（每个 dev doc 结构：背景→方案→数据流→边界情况→配置项），最后精简 README.md 指向新目录

**Tech Stack:** Markdown only, no code changes

---

### Task 1: 创建目录结构 + 归档 PROGRESS.md

**Files:**
- Create: `Docs/user/`
- Create: `Docs/dev/`
- Create: `Docs/ops/`
- Create: `Docs/archive/`
- Move: `PROGRESS.md` → `Docs/archive/PROGRESS.md`

- [ ] **Step 1: 创建目录**

```bash
mkdir -p Docs/user Docs/dev Docs/ops Docs/archive
```

- [ ] **Step 2: 归档 PROGRESS.md**

```bash
git mv PROGRESS.md Docs/archive/PROGRESS.md
```

- [ ] **Step 3: 提交**

```bash
git add Docs/ PROGRESS.md
git commit -m "docs: create Docs/ directory structure, archive PROGRESS.md"
```

---

### Task 2: 用户文档 — features.md + commands.md

**Files:**
- Create: `Docs/user/features.md`
- Create: `Docs/user/commands.md`

**素材来源:** README.md 功能总览 + arteta_help.py 指令列表 + PROGRESS.md 使用说明章节

- [ ] **Step 1: 写 features.md**

内容大纲：
- 项目一句话介绍（阿尔特塔 QQ 机器人）
- 每个功能一句话说明（AI对话、理科解题、图片生成、英超积分榜、好感度系统、誓言系统、点赞、禁言管理、日报、周报）
- 末尾指向 `commands.md` 和 `Docs/dev/`

- [ ] **Step 2: 写 commands.md**

内容大纲：
- 指令速查表，三列：指令、别名、功能说明
- 来源：`arteta_help.py:12-31` 的 help_text，整理为表格

```markdown
| 指令 | 别名 | 说明 |
|------|------|------|
| A / 塔子 / 阿尔特塔 + 内容 | — | AI 对话 |
| 算法 + 题目 | 数学、物理、计算 | 理科解题 |
| 画图 + 描述 | — | AI 图片生成 |
| ... | ... | ... |
```

- [ ] **Step 3: 提交**

```bash
git add Docs/user/
git commit -m "docs: add user docs (features + commands)"
```

---

### Task 3: 架构概览 — dev/overview.md

**Files:**
- Create: `Docs/dev/overview.md`

**素材来源:** PROGRESS.md 项目概述 + README.md 项目结构 + 实际代码文件职责

- [ ] **Step 1: 写 overview.md**

内容：
- **项目定位**：基于 NoneBot2 + OneBot V11 的 QQ 群聊机器人
- **技术栈**：NoneBot2 / DeepSeek / SQLite / ChromaDB / Playwright / Pillow
- **文件职责表**：

| 文件 | 职责 |
|------|------|
| `bot.py` | 启动入口、日志配置 |
| `plugins/arteta_chat.py` | AI 对话核心、好感度标记、渲染路由 |
| `plugins/arteta_tools.py` | Function Calling 工具注册 |
| `plugins/arteta_memory.py` | ChromaDB 向量记忆 |
| ... | ... |

- **数据流图（文字版）**：用户输入 → arteta_chat.py 处理 → LLM 调用 → 好感度评估 → 记忆存储 → 渲染输出
- **数据库表概览**：players / messages / nicknames / profile_updates / daily_likes / member_relations / chromadb

- [ ] **Step 2: 提交**

```bash
git add Docs/dev/overview.md
git commit -m "docs: add project architecture overview"
```

---

### Task 4: AI 对话 + LLM 集成 — dev/chat-llm.md

**Files:**
- Create: `Docs/dev/chat-llm.md`

**素材来源:** PROGRESS.md 人格优化章节 + arteta_chat.py prompt 部分 + arteta_tools.py

- [ ] **Step 1: 写 chat-llm.md**

内容：
- **背景**：从被动注入赛果到 Function Calling 按需获取
- **架构**：用户输入 → process_chat() → base_prompt 构建（含更衣室概况/群成员/历史相关记忆）→ run_tool_loop() → LLM 回复 → 好感度标记提取 → 红字渲染
- **Function Calling 工具表**：get_arsenal_result / get_pl_table / get_arsenal_injuries / search_news / get_football_knowledge / get_group_members / get_member_relations
- **Prompt 结构**：ARTETA_PROMPT 常量 + base_prompt 动态注入
- **边界情况**：reasoning_content 回传、FinishedException 保护、超时后台任务

- [ ] **Step 2: 提交**

---

### Task 5: 好感度系统 — dev/favorability.md

**Files:**
- Create: `Docs/dev/favorability.md`

**素材来源:** PROGRESS.md 好感度相关全部章节 (5月6日改造、5月7日重写)

- [ ] **Step 1: 写 favorability.md**

内容：
- **背景**：从纯关键词匹配到 LLM 标记为主、关键词为辅的双架构
- **架构**：LLM 回复 → extract_favor_marker() 提取标记 → apply_favor_change() 计算 delta → check_keyword_penalty() 额外扣分 → 数据库更新 → 红字拼接
- **标记系统**：7 级 FAVOR_MARKERS（+++/++/+/=/-/--/---），每个对应分数范围
- **关键词辅助扣分**：重度(-80~-40) / 中度(-40~-15) / 轻度(-20~-5)
- **等级阈值**：传奇队长≥500 / 核心首发≥200 / 一线队≥50 / 青训生≥0 / 预备队≥-50 / 看台内鬼<-50
- **数据库字段**：players.favorability / players.level

- [ ] **Step 2: 提交**

---

### Task 6: 誓言系统 — dev/swear.md

**Files:**
- Create: `Docs/dev/swear.md`

**素材来源:** PROGRESS.md 发誓功能章节 + arteta_swear.py

- [ ] **Step 1: 写 swear.md**

内容：
- 数据库 `swear_records` 表结构
- 命令：`发誓` / `我的誓言` / `发誓 /CLEAR`
- 存储逻辑和查询逻辑

- [ ] **Step 2: 提交**

---

### Task 7: 个人档案 + 人格画像 — dev/profile.md

**Files:**
- Create: `Docs/dev/profile.md`

**素材来源:** PROGRESS.md 5月4日档案系统 + 5月4日人格画像

- [ ] **Step 1: 写 profile.md**

内容：
- **个人档案**：nicknames 表 / messages 表 / `/档案` 命令
- **人格画像**：players.profile_json 字段 JSON 结构 / profile_updates 表 / 更新触发策略（3条初始化、每5条更新、24h 超时、10min 冷却）
- LLM 分析用户消息生成画像的流程

- [ ] **Step 2: 提交**

---

### Task 8: AI 图片生成 — dev/image-generation.md

**Files:**
- Create: `Docs/dev/image-generation.md`

**素材来源:** PROGRESS.md 提及 + arteta_image.py

- [ ] **Step 1: 写 image-generation.md**

内容：
- `画图` 命令：gpt-image-2 图片生成
- `画图-pro`：独立 API endpoint
- 配置项：IMAGE_API_KEY / IMAGE_API_URL / IMAGE_MODEL

- [ ] **Step 2: 提交**

---

### Task 9: 理科解题 + 渲染管道 — dev/science.md

**Files:**
- Create: `Docs/dev/science.md`

**素材来源:** PROGRESS.md 5月5日渲染管道章节 + arteta_render.py + arteta_cmath.py

- [ ] **Step 1: 写 science.md**

内容：
- **双渲染架构**：needs_html_render() 检测 → html_to_image() (Playwright+KaTeX) → fallback text_to_tactical_board() (PIL)
- **关键函数**：html_to_image() / needs_html_render() / normalize_math_delimiters() / text_to_tactical_board()
- **模板**：templates/arteta_render.html（KaTeX + highlight.js + marked.js）
- **爬坑**：Python raw string bug / f-string 冲突 / quality=95 与 PNG 冲突 / matplotlib usetex 与中文冲突 / PIL 回退

- [ ] **Step 2: 提交**

---

### Task 10: 每日群聊总结 — dev/daily-summary.md

**Files:**
- Create: `Docs/dev/daily-summary.md`

**素材来源:** PROGRESS.md 5月4日日报章节 + arteta_daily.py

- [ ] **Step 1: 写 daily-summary.md**

内容：
- 定时任务：每天 22:30 APScheduler cron
- 手动触发：`/今日总结` / `/日报`
- 数据流：daily_messages 表存储 → LLM 生成总结 → render 发布
- 自动清理 7 天前的消息

- [ ] **Step 2: 提交**

---

### Task 11: 阿森纳周报 — dev/weekly-news.md

**Files:**
- Create: `Docs/dev/weekly-news.md`

**素材来源:** PROGRESS.md 5月9日周报章节 + arteta_weekly.py

- [ ] **Step 1: 写 weekly-news.md**

内容：
- **爬虫**：多源并发（BBC/Sky/Guardian）→ fetch_article_content() → 去重 → Top 8
- **处理**：DeepSeek 生成 → save_to_knowledge_base() 注入知识库 → clear_cache()
- **发布**：publish_to_groups() → render → 全群发送
- **定时**：每周一 09:00 APScheduler
- **爬坑**：str\|None 兼容、BBC 超时补偿、知识库缓存失效、颜色标记回退清理

- [ ] **Step 2: 提交**

---

### Task 12: ChromaDB 群体记忆 — dev/chromadb-memory.md

**Files:**
- Create: `Docs/dev/chromadb-memory.md`

**素材来源:** PROGRESS.md 5月9日 ChromaDB 章节 + arteta_memory.py

- [ ] **Step 1: 写 chromadb-memory.md**

内容：
- **架构**：MemoryStore 类（initialize / add_memory / query_memories）
- **Collection**：group_memories，metadata filter 按群隔离，all-MiniLM-L6-v2 384维
- **检索策略**：每次对话语义检索 Top 5 → 注入 `【相关历史对话（本群）】`
- **写入时机**：LLM 回复后、好感度红字拼接前
- **爬坑**：sqlite3 版本 monkey-patch / posthog 降级 / import 重复 / 后台任务异常保护

- [ ] **Step 2: 提交**

---

### Task 13: 群成员认知系统 — dev/member-recognition.md

**Files:**
- Create: `Docs/dev/member-recognition.md`

**素材来源:** PROGRESS.md 5月7日群成员认知章节

- [ ] **Step 1: 写 member-recognition.md**

内容：
- member_relations 表：记录回复/@ 互动关系
- Function Calling 工具：get_group_members() / get_member_relations()
- Prompt 注入：更衣室概况 Top 8 活跃球员

- [ ] **Step 2: 提交**

---

### Task 14: 好感度排行 + QQ 赞 — dev/ranking.md + dev/like-system.md

**Files:**
- Create: `Docs/dev/ranking.md`
- Create: `Docs/dev/like-system.md`

- [ ] **Step 1: 写 ranking.md**

内容：
- matplotlib 横向柱状图 TOP10/BOTTOM10
- 关键实现：usetex 临时关闭、颜色 hex 而非 RGB、边距自适应
- 管理员不参与排行

- [ ] **Step 2: 写 like-system.md**

内容：
- QQ 名片赞 API：send_like
- 每日限额：普通 10 / VIP 50
- VIP 检测：get_group_member_info 检查 is_vip/vip_level，群管理自动 VIP
- 数据库 daily_likes 表
- 阿尔特塔风格语录

- [ ] **Step 3: 提交**

```bash
git add Docs/dev/ranking.md Docs/dev/like-system.md
git commit -m "docs: add ranking and like-system dev docs"
```

---

### Task 15: 运维文档 — ops/deployment.md + ops/server-setup.md

**Files:**
- Create: `Docs/ops/deployment.md`
- Create: `Docs/ops/server-setup.md`

**素材来源:** README.md 部署部分 + deploy/README.md + deploy/deploy_ecs.sh + deploy/deploy_docker.sh

- [ ] **Step 1: 写 deployment.md**

内容：
- **前置条件**：Python 3.8+、NapCat QQ、API Key
- **本地部署**：pip install → cp .env → 启动
- **ECS 部署**：从 deploy_ecs.sh 提取完整步骤（上传→编辑→运行→NapCat→配置→启动）
- **Docker 部署**：从 deploy_docker.sh 提取步骤
- **进程管理**：supervisorctl 命令
- **安全组**：端口配置建议
- **数据库备份**：自动备份策略

- [ ] **Step 2: 写 server-setup.md**

内容：
- Playwright Chromium 安装：`playwright install --with-deps chromium`
- 系统依赖：xvfb / libgtk-3 / libnss3 等
- 字体文件：msyh.ttc 获取和放置
- 日志目录：`/opt/arteta_bot/logs/` 创建和权限设置
- `.env.prod` 配置项说明

- [ ] **Step 3: 提交**

```bash
git add Docs/ops/deployment.md Docs/ops/server-setup.md
git commit -m "docs: add ops deployment and server-setup docs"
```

---

### Task 16: 运维文档 — ops/logging.md + ops/troubleshooting.md

**Files:**
- Create: `Docs/ops/logging.md`
- Create: `Docs/ops/troubleshooting.md`

**素材来源:** bot.py + loguru 设计 spec + PROGRESS.md 各章节爬坑记录

- [ ] **Step 1: 写 logging.md**

内容：
- **架构**：loguru + InterceptHandler 桥接标准 logging
- **配置**：文件 sink (DEBUG, 10MB轮转, 保留5份) + 终端 sink (生产INFO/开发DEBUG, 彩色)
- **环境切换**：ENVIRONMENT 环境变量控制路径和级别
- **使用方式**：原生 loguru（新插件） vs 标准 logging 桥接（旧插件）
- **日志格式**：时间戳 | 级别 | 模块:行号 | 消息
- **查看方式**：`supervisorctl tail -f arteta_bot` / `tail -f logs/arteta_bot.log`

- [ ] **Step 2: 写 troubleshooting.md**

内容（按类别汇总 PROGRESS.md 各章节爬坑）：
- **部署环境**：Python 3.8 兼容（dict[str, X] → Dict[str, X]、str\|None → Optional[str]）
- **ChromaDB**：sqlite3 版本要求 / posthog 版本降级
- **渲染**：raw string tokenizer bug / f-string 冲突 / Playwright quality+PNG / matplotlib color range
- **网络**：BBC ConnectTimeout / QQ CDN HTTPS 403
- **容器**：文件路径隔离 / Docker volume hash
- **NoneBot**：插件加载失败排查 / FinishedException 误捕获

- [ ] **Step 3: 提交**

```bash
git add Docs/ops/logging.md Docs/ops/troubleshooting.md
git commit -m "docs: add logging and troubleshooting ops docs"
```

---

### Task 17: 精简 README.md 指向 Docs/

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 重写 README.md**

保留：
- 项目一句话介绍
- 核心指令速查（精简版，5-8 条）
- 快速开始（一句 "见 Docs/ops/deployment.md"）
- 指向 Docs/ 各目录的导航

去掉：
- 完整部署方法（移到 Docs/ops/deployment.md）
- 完整项目结构（移到 Docs/dev/overview.md）
- 完整功能描述（移到 Docs/user/features.md）

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs: simplify README to point to Docs/ directory"
```
