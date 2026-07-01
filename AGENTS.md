# Arteta Bot — AGENTS.md

基于 NoneBot2 + OneBot V11 (NapCat) 的 QQ 群聊机器人，模拟阿森纳主教练米克尔·阿尔特塔。启动入口 `bot.py`，所有业务逻辑在 `plugins/` 目录下。

## 目录速览

```
arteta_bot/
├── bot.py                 # 启动入口 + loguru 日志配置
├── pyproject.toml         # 依赖声明
├── README.md              # 快速入口，指向 Docs/
├── AGENTS.md              # ← 你在这里
│
├── plugins/               # 所有功能插件（核心代码）
│   ├── arteta_chat.py     # AI 对话核心 + 好感度 + 渲染路由
│   ├── arteta_tools.py    # Function Calling 工具 (8个)
│   ├── arteta_memory.py   # ChromaDB 向量记忆
│   ├── arteta_vision.py   # 纯 vision API 调用层（不依赖 NoneBot，dashboard 共用）
│   ├── arteta_mute.py     # 塔闭嘴/塔说话 群静音开关
│   ├── arteta_render.py   # 图片渲染引擎 (PIL + Playwright)
│   ├── arteta_knowledge.py # 本地知识库检索
│   ├── arteta_daily.py    # 每日群聊总结
│   ├── arteta_weekly.py   # 阿森纳周报（爬虫 + LLM）
│   ├── arteta_football_news.py # 全局足球新闻向量库（定时抓取 + ChromaDB）
│   ├── arteta_swear.py    # 誓言系统
│   ├── arteta_like.py     # QQ 名片赞
│   ├── arteta_image.py    # AI 图片生成
│   ├── arteta_admin.py    # 管理员/禁言
│   ├── arteta_standings.py # 英超积分榜
│   ├── arteta_cmath.py    # 理科解题渲染
│   └── arteta_help.py     # 帮助菜单
│
├── Docs/                  # 项目文档（统一文档树）
│   ├── user/              # 用户文档
│   ├── dev/               # 开发者文档
│   ├── ops/               # 运维文档
│   └── archive/           # 原始 PROGRESS.md 留底
│
├── knowledge_base/        # LLM 本地知识库 (.md 文件)
├── templates/             # HTML 渲染模板 (KaTeX + marked.js)
├── deploy/                # 部署脚本 (Docker / ECS)
└── logs/                  # 运行时日志 (loguru, 10MB 轮转)
```

## 核心架构

### 数据流（对话处理）

```
用户输入 → on_command 触发 (A/塔子/阿尔特塔)
  → process_chat()
    → get_player_data()          # 获取用户好感度/等级
    → 构建 base_prompt            # 角色设定 + 更衣室概况 + 相关记忆
    → run_tool_loop()            # Function Calling 最多 5 轮
    → LLM 回复 → 提取好感度标记   # extract_favor_marker()
    → 关键词辅助扣分              # check_keyword_penalty()
    → 更新数据库                 # apply_favor_change()
    → 存入 ChromaDB              # add_memory()
    → 渲染输出                   # html_to_image / PIL fallback
```

### 好感度系统（双架构）

- **主系统**: LLM 在回复末尾输出 `【好感度+】/【好感度-】` 等 7 级标记
- **辅助**: 关键词列表额外扣分（重度 -80~-40 / 中度 -40~-15 / 轻度 -20~-5）
- **等级**: 传奇队长≥500 / 核心首发≥200 / 一线队≥50 / 青训生≥0 / 预备队≥-50 / 看台内鬼<-50
- 管理员不参与好感度变动

### Function Calling 工具（arteta_tools.py）

| 工具 | 触发场景 | 数据源 |
|------|---------|--------|
| get_arsenal_result | 比赛结果/比分 | football-data.org |
| get_pl_table | 积分榜/排名 | football-data.org |
| get_arsenal_injuries | 伤病名单 | football-data.org |
| search_news(q) | 新闻/转会 | DuckDuckGo |
| search_football_news(query, category, days) | 最近英超/欧冠/五大联赛/中超新闻 | ChromaDB `football_news` collection |
| get_football_knowledge(topic) | 战术/知识 | knowledge_base/ |
| get_group_members(group_id) | 群成员列表 | SQLite |
| get_member_relations(group_id, user_id) | 成员关系 | SQLite |

### 数据库

- **`arsenal_data.db`** (SQLite): players, nicknames, messages, profile_updates, member_relations, daily_likes, daily_messages, football_news_items
- **`chroma_db/`** (ChromaDB): `group_memories`、`football_news` collections, all-MiniLM-L6-v2 384维
- **`data/arteta_swears.json`**: 誓言存储

### 日志系统（bot.py）

- loguru + InterceptHandler 桥接标准 logging
- 文件 sink: DEBUG+, 10MB 轮转, 保留 5 份
- 终端 sink: 生产 INFO+ / 开发 DEBUG+, 彩色
- 环境切换: `ENVIRONMENT` 控制路径和级别

## 关键 Python 版本约束

- Python **3.8** 兼容（线上服务器版本）
- 不支持 `dict[str, X]` → 用 `Dict[str, X]`
- 不支持 `str | None` → 用 `Optional[str]`
- ChromaDB 需要 `pysqlite3-binary` monkey-patch `sys.modules["sqlite3"]`

## 开发流程

### 修改代码

1. 直接在 `plugins/` 下修改对应文件
2. `arteta_chat.py` 是最大的文件（~1400 行），修改时注意函数边界
3. 新增功能按职责创建新插件文件，不要塞进 arteta_chat.py
4. 本地测试: `python bot.py`（需要 NapCat QQ 运行）
5. 记得同步更新 `Docs/dev/` 下对应的文档

### 提交规范

```
feat: 新功能
fix: 修复
refactor: 重构
docs: 文档
```

### 部署（线上 ECS）

```
# 上传修改的文件到 /opt/arteta_bot/
scp plugins/xxx.py arteta@host:/opt/arteta_bot/plugins/

# 重启
supervisorctl restart arteta_bot

# 查看日志
supervisorctl tail -f arteta_bot
```

首次部署参考 `Docs/ops/deployment.md`。

## 当前开发进度（2026-06-20）

### 2026-06-20 修复三轮

**1. Vision API 图片截断**：
- `max_tokens` 500→2048，避免描述中途截断
- 新增 `_normalize_image_data_url()`：大图超过 2048px 等比缩放 + 转 JPEG 85%
- 涉及文件：`plugins/arteta_vision.py`

**2. ChromaDB 大模型发言截断**：
- `MAX_DOC_LENGTH=1000` 从末尾截断导致 Assistant 发言经常被完全丢弃
- 改为 40/60 分别截断 User/Assistant，确保两部分都被保留
- `/算法` 路径补上 `add_memory()`（原来完全没有）
- 涉及文件：`plugins/arteta_memory.py`、`plugins/arteta_chat.py`、`dashboard/api/services/bot_chat_service.py`

**3. NapCat QQ 离线排障**：
- QQ 机器人账号掉线时，重启 bot 进程无效，需 `docker restart napcat`
- 公网扫描流量源：Dashboard（8765）和 bot（8088）端口暴露
- 建议安全组限制 8088→127.0.0.1，8765→可信 IP
- 写入 `Docs/ops/troubleshooting.md`

### 开发者功能验证工具已落地

- 新增本地验证入口：`tools/verify_features.py`
- 默认输出目录：`artifacts/verify/<timestamp>/`
- 已支持 suites：`core`、`all`、`render`、`memory`、`chat`、`commands`、`football_news`、`online`
- 已补充 fixtures：`tests/fixtures/markdown/`、`tests/fixtures/knowledge/`、`tests/fixtures/images/`
- 已抽出可复用 helper：
  - `plugins/arteta_image.py` → `preprocess_reference_image()`
  - `plugins/arteta_like.py` → `get_daily_like_limit()`
  - `plugins/arteta_help.py` → `build_help_text()`
- 已支持隔离路径覆盖：
  - `ARTETA_DB_PATH`
  - `ARTETA_CHROMA_DIR`
  - `ARTETA_SWEARS_FILE`

### 当前验证状态

- `chat` suite 可本地通过
- `memory` suite 在安装 `chromadb` 后可本地通过
- `commands` suite 在安装 `chromadb` 后可本地通过
- `render` 中的非浏览器项（模板、战术板 PNG、引用图预处理）可本地通过
- `render/html_to_image` 依赖 Playwright Chromium；未安装时该 case 会标记为 `skipped`
- 如需实际验证 HTML/Markdown 图片渲染，先执行：`python -m playwright install chromium`

### 常用验证命令

```bash
python tools/verify_features.py
python tools/verify_features.py --suite all
python tools/verify_features.py --suite core --online
python tools/verify_features.py --suite render --case html_to_image
python tools/verify_features.py --suite football_news
python tools/verify_features.py --list-suites
```

对应说明文档：`Docs/dev/developer-verification.md`

### Dashboard 与 Bot 共用 Vision（2026-05-27）

- `plugins/arteta_vision.py` 是无 NoneBot 依赖的 vision 模块；`plugins/arteta_chat.py` 与 `dashboard/api/services/bot_chat_service.py` 都从这里导入 `analyze_image_base64` / `VisionConfig`
- Dashboard 是独立 uvicorn 进程，**不要**让它直接 import `plugins.arteta_chat` 或其它带 `on_command()` 的 plugin —— 会触发 `NoneBot has not been initialized` 500
- `dashboard/api/services/prompt_service.py` `DEFAULT_PROMPTS` 内置 6 段默认 prompt content；`get_prompt(...)` 仍以调用方传入的 `default` 参数为准，避免 service content 与 plugin 常量漂移
- `/算法` 命令的 reply 引用图片现在会经 `fetch_quoted_chain` 解析（与 `process_chat` 一致）

## 修改后 Checklist

每次修改完成后确认以下事项：

- [ ] 本地 `python bot.py` 启动测试通过
- [ ] Python 3.8 兼容性（用了 `dict[str, X]` 或 `str | None`？）
- [ ] 对应的 `Docs/dev/` 文档已更新
- [ ] 是否需要更新 `README.md` 或 `Docs/user/commands.md`（新增/修改指令时）
- [ ] `.env.dev` 是否添加了新配置项（需要告知部署者）
- [ ] 数据库变更是否需要迁移脚本
- [ ] 新依赖是否有 Python 3.8 兼容的版本

## 常见问题

- **ChromaDB 报错**: 检查 sqlite3 版本（需 ≥ 3.35.0），`pysqlite3-binary` 是否已安装
- **图片渲染失败**: 检查 Playwright Chromium 是否安装（`playwright install --with-deps chromium`）
- **WebSocket 断联**: 检查 `asyncio.create_task()` 后台任务是否正确 try/except
- **服务器中文方块**: 检查 `msyh.ttc` 字体文件是否存在
- **插件加载失败**: `nonebot.load_plugins` 会在日志输出具体错误，看 `logs/arteta_bot.log`

## 工作记录：2026-06-22 Vision 识别修复

### 背景

用户反馈 QQ 图片识别再次失败，并且曾在 Dashboard 把 Vision 模型改成 Qwen 后感觉没有生效。线上排查确认：

- QQ/NapCat 图片链路正常：`bot.get_msg()` 和 `bot.get_image()` 均可拿到图片 URL。
- 问题图片可下载，原图为 `1272x3762` 长截图，预处理后约 `692x2048`、`230KB`。
- SiliconFlow `Qwen/Qwen3-VL-32B-Instruct` 对该长图 30 秒读超时；同一请求超时放宽到 60 秒后约 35.5 秒成功返回。
- Dashboard 写入的 `VISION_MODEL=qwen3.7-plus` 已保存到 `.env.prod`，Bot 启动时也读到了，但旧实现先固定调用 SiliconFlow，Dashboard 配置只作为 fallback，因此看起来“没生效”。

### 修复

- `plugins/arteta_vision.py`
  - 改为优先调用 `.env` / Dashboard 配置的 `VISION_API_URL`、`VISION_API_KEY`、`VISION_MODEL`。
  - SiliconFlow 改为 fallback。
  - 新增 `VisionConfig.vision_timeout`，默认 `60.0` 秒。
  - 保留图片最长边 2048px 缩放与 `max_tokens=2048`。
- `plugins/arteta_chat.py`
  - 新增读取 `VISION_TIMEOUT` 并传入 `VisionConfig`。
- `dashboard/api/config.py`
  - `ENV_WHITELIST` 新增 `VISION_TIMEOUT`。
- `dashboard/api/services/bot_chat_service.py`
  - Dashboard Bot Chat 构造 `VisionConfig` 时读取 `VISION_TIMEOUT`。
- `bot.py`
  - 对 `Loaded Config` 等日志中的 `*_key`、`*_token`、`*_secret`、`*_password` 做脱敏，避免再次写入明文密钥。
- `.env.prod`
  - 线上已加入 `VISION_TIMEOUT=60`。

### 线上部署与验证

- 线上备份目录：`/opt/arteta_bot/backups/vision_fix_20260622192153`
- 已重启：
  - `supervisorctl restart arteta_bot`
  - `supervisorctl restart arteta_dashboard`
- 服务状态：
  - `arteta_bot RUNNING`
  - `arteta_dashboard RUNNING`
- 线上最小 Vision 验证结果：
  - 实际调用链只有 `https://ws-lh6czfcameqkzr8g.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`
  - 模型为 `qwen3.7-plus`
  - timeout 为 `60.0`
  - 未先调用 SiliconFlow
- 最新启动日志确认密钥已脱敏为 `<masked>`。

### 本地验证

```bash
python -m pytest tests/test_arteta_vision_config.py tests/test_arteta_chat_vision.py tests/dashboard/test_dashboard_config.py tests/dashboard/test_env_service.py tests/dashboard/test_bot_chat.py -q
```

结果：`31 passed`。

### 后续注意

- 旧日志中已经出现过明文 API key，建议后续清理/轮转旧日志，并逐步更换已暴露的 key。
- 如果再次出现长图识别失败，优先检查 `VISION_TIMEOUT`、`VISION_API_URL` 和实际调用日志，而不是先重启 NapCat。
