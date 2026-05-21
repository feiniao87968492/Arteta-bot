# Arteta Bot — 阿森纳 QQ 群聊机器人

基于 NoneBot2 + OneBot V11 的 QQ 群聊机器人，以阿森纳主教练米克尔·阿尔特塔的身份与群成员互动。内置 DeepSeek 大语言模型对话、本地知识库、英超积分查询、AI 图片生成、好感度系统等功能。

## 快速开始

```bash
pip install nonebot2 nonebot-adapter-onebot nonebot-plugin-apscheduler httpx aiosqlite pillow pilmoji duckduckgo_search loguru
cp .env.dev .env  # 编辑 API Key
python bot.py
```

> 完整部署指南见 [Docs/ops/deployment.md](Docs/ops/deployment.md)

## 指令速查

- `A/塔子/阿尔特塔 [内容]` — AI 对话
- `算法 [题目]` — 理科解题
- `画图 [描述]` — AI 图片生成
- `英超局势` — 英超积分榜
- `好感度` / `档案` / `盒` — 好感度系统
- `赞我` — QQ 名片赞
- `发誓 [目标]` — 誓言系统
- `帮助` — 帮助菜单

> 完整指令表见 [Docs/user/commands.md](Docs/user/commands.md)

## 文档导航

- 📖 [用户文档](Docs/user/features.md) — 功能概览与指令表
- 🔧 [开发者文档](Docs/dev/overview.md) — 架构说明与功能实现
- 🧪 [开发者验证](Docs/dev/developer-verification.md) — 本地功能回归与验收脚本
- 🚀 [运维文档](Docs/ops/deployment.md) — 部署与环境配置

## 项目状态

活跃开发中
