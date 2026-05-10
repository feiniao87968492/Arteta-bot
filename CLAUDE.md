# Arteta Bot — CLAUDE.md

基于 NoneBot2 + OneBot V11 (NapCat) 的 QQ 群聊机器人，模拟阿森纳主教练米克尔·阿尔特塔。启动入口 `bot.py`，所有业务逻辑在 `plugins/` 目录下。

## 目录速览

```
arteta_bot/
├── bot.py                 # 启动入口 + loguru 日志配置
├── pyproject.toml         # 依赖声明
├── README.md              # 快速入口，指向 Docs/
├── CLAUDE.md              # ← 你在这里
│
├── plugins/               # 所有功能插件（核心代码）
│   ├── arteta_chat.py     # AI 对话核心 + 好感度 + 渲染路由
│   ├── arteta_tools.py    # Function Calling 工具 (7个)
│   ├── arteta_memory.py   # ChromaDB 向量记忆
│   ├── arteta_render.py   # 图片渲染引擎 (PIL + Playwright)
│   ├── arteta_knowledge.py # 本地知识库检索
│   ├── arteta_daily.py    # 每日群聊总结
│   ├── arteta_weekly.py   # 阿森纳周报（爬虫 + LLM）
│   ├── arteta_swear.py    # 誓言系统
│   ├── arteta_like.py     # QQ 名片赞
│   ├── arteta_image.py    # AI 图片生成
│   ├── arteta_admin.py    # 管理员/禁言
│   ├── arteta_standings.py # 英超积分榜
│   ├── arteta_cmath.py    # 理科解题渲染
│   └── arteta_help.py     # 帮助菜单
│
├── Docs/                  # 项目文档
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
| get_football_knowledge(topic) | 战术/知识 | knowledge_base/ |
| get_group_members(group_id) | 群成员列表 | SQLite |
| get_member_relations(group_id, user_id) | 成员关系 | SQLite |

### 数据库

- **`arsenal_data.db`** (SQLite): players, nicknames, messages, profile_updates, member_relations, daily_likes, daily_messages
- **`chroma_db/`** (ChromaDB): `group_memories` collection, all-MiniLM-L6-v2 384维
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
