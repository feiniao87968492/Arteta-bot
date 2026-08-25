# Docs 目录重组设计

## 目标

新建 `Docs/` 目录，将现有 841 行的 `PROGRESS.md` 按功能点拆分为独立、可读的文档，并补充运维文档，形成清晰的用户/开发者/运维三层结构。

## 动机

- `PROGRESS.md` 混合了项目概述、功能修改记录、部署记录、使用说明，边界模糊，841 行难以快速定位
- `README.md` 部署方法嵌入在功能描述中，不够独立
- 现有的 `docs/superpowers/specs/` 和 `docs/superpowers/plans/` 是 brainstorming 工作流产物，不适合作为项目文档

## 目录结构

```
Docs/
├── user/                    # 用户文档
│   ├── features.md          # 功能总览 + 一句话介绍
│   └── commands.md          # 完整指令速查表
├── dev/                     # 开发者文档
│   ├── overview.md          # 项目架构：流程、文件职责、数据流
│   ├── chat-llm.md          # AI 对话 + LLM 集成 + Function Calling
│   ├── favorability.md      # 好感度系统（关键词+LLM标记双架构）
│   ├── swear.md             # 誓言系统
│   ├── profile.md           # 个人档案 + 人格画像
│   ├── image-generation.md  # AI 图片生成（gpt-image-2）
│   ├── science.md           # 理科解题 + LaTeX/HTML/Playwright 渲染管道
│   ├── daily-summary.md     # 每日群聊总结
│   ├── weekly-news.md       # 阿森纳周报（爬虫+LLM生成+定时发布）
│   ├── chromadb-memory.md   # ChromaDB 群体记忆（向量检索）
│   ├── member-recognition.md # 群成员认知系统（关系追踪）
│   ├── ranking.md           # 好感度排行柱状图
│   └── like-system.md       # QQ 名片赞
├── ops/                     # 运维文档
│   ├── deployment.md        # 部署步骤（本地/Docker/ECS）
│   ├── server-setup.md      # 服务器环境（Playwright、字体、系统依赖）
│   ├── logging.md           # 日志系统（loguru）
│   └── troubleshooting.md   # 爬坑记录汇总 + 常见问题
└── archive/
    └── PROGRESS.md          # 原始文件留底
```

## 文档写作规范

每篇 dev/ 下功能文档的结构：
- **背景** — 为什么需要这个功能
- **方案** — 做了什么、怎么做的
- **关键数据流/代码结构** — 流程图或伪代码
- **边界情况** — 特殊处理的场景
- **配置项** — 环境变量、数据库表等

ops/ 下文档的结构：
- **前置条件** — 需要什么依赖
- **步骤** — 可复现的操作流程
- **验证方法** — 怎么确认部署成功

## 素材来源

| 目标文档 | 素材来源 |
|---------|---------|
| user/* | README.md（精简搬运） |
| dev/* | PROGRESS.md 各章节 + docs/superpowers/specs/ |
| ops/deployment.md | README.md 部署部分 + deploy/* |
| ops/logging.md | bot.py + docs/superpowers/specs/ 日志设计 |
| archive/PROGRESS.md | PROGRESS.md（原样保留） |

## 不涉及

- 不修改 `docs/superpowers/` 现有 brainstorming 产物
- 不修改 `plugins/` 或 `bot.py` 等代码文件
- 不修改 `.env` 或 `pyproject.toml` 等配置
