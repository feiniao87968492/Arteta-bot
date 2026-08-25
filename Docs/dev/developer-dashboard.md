# Developer Mission Control Dashboard

开发者前端是 Arteta Bot 的内网维护面板，用于查看群聊档案、管理 ChromaDB 记忆、运行本地功能验证、浏览文档库、查看日志和脱敏配置 API Key。

## 架构

```text
dashboard/
  api/        FastAPI 管理后端
  web/        React + Vite + TypeScript 前端
```

后端是唯一能访问 SQLite、ChromaDB、日志、文档、环境文件和验证脚本的层。浏览器在封面页点击“开始”后必须使用管理员密码登录，登录成功才会进入控制台。Provider 配置接口要求有效 Dashboard Bearer token，并由服务器运行环境和群组访问密码提供额外访问边界。

## ECS 生产运行模式

生产推荐将 Dashboard 直接部署在 ECS 上运行，而不是在本地同步 SQLite 副本。ECS 模式下：

- 群聊档案读取和写入 `/opt/arteta_bot/arsenal_data.db`
- 记忆管理读取和删除 `/opt/arteta_bot/chroma_db`
- 实时日志读取 `/opt/arteta_bot/logs`
- 配置密钥读取和更新 `/opt/arteta_bot/.env`
- 前端由 FastAPI 托管 `dashboard/web/dist`

关键环境变量：

```bash
DASHBOARD_PUBLIC=true
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8765
ARTETA_DB_PATH=/opt/arteta_bot/arsenal_data.db
ARTETA_CHROMA_DIR=/opt/arteta_bot/chroma_db
DASHBOARD_LOGS_DIR=/opt/arteta_bot/logs
DASHBOARD_ENV_FILE=/opt/arteta_bot/.env.prod
DASHBOARD_WEB_DIST=/opt/arteta_bot/dashboard/web/dist
DASHBOARD_ADMIN_PASSWORD=<strong-admin-password>
DASHBOARD_SECRET_KEY=<long-random-secret>
ARTETA_PROMPTS_FILE=/opt/arteta_bot/config/prompts.json
```

`DASHBOARD_ADMIN_PASSWORD` 用于登录校验，`DASHBOARD_SECRET_KEY` 用于签发和验证登录 JWT。在 `DASHBOARD_PUBLIC=true` 的生产环境中，两者都必须设置为非空强随机值；不要将真实值提交到仓库。

`start_dashboard.ps1 -EcsSync` 仍可用于本地只读排障，但不再是生产管理主路径。

## 本地开发

启动 API：

```bash
python -m uvicorn dashboard.api.main:app --reload --port 8765
```

启动前端：

```bash
cd dashboard/web
npm install
npm run dev
```

打开 Vite 输出的本地地址，点击封面页“开始”，然后使用 `DASHBOARD_ADMIN_PASSWORD` 登录进入控制台。

## 功能模块

- Mission Control：首页状态总览，显示 SQLite、ChromaDB、日志、配置和最近验证结果。
- Chroma Memory：按群查看和搜索记忆，支持单条/批量删除。
- Verify Center：选择 suite/case 运行 `tools/verify_features.py`，实时查看输出并读取最新报告。
- Docs Library：浏览 `docs/` 和 `knowledge_base/`，支持 Markdown 内容查看和搜索。
- Live Logs：查看允许目录下的日志文件并按级别/关键词过滤；进入页面后默认读取当前日志尾部。
- Config：脱敏查看白名单 API Key，并通过完整新值替换保存；保存后会同步 Dashboard API 当前进程环境，行内“测试”按钮可确认文件值与 Dashboard API 运行值是否一致，QQ Bot 主进程可通过页面上的“重启 QQ Bot”按钮触发固定的 `supervisorctl restart arteta_bot` 来重新读取启动期配置；编辑框使用明文输入，不用密码星号。包含算法、图片生成和图片识别（`VISION_API_KEY` / `VISION_API_URL` / `VISION_MODEL`）相关配置。`VISION_API_URL` 以 `/anthropic` 结尾时，机器人图片识别会使用 Anthropic Messages 格式调用 `/v1/messages`；小米 MiMo 地址（如 `https://api.xiaomimimo.com/v1`）使用官方 OpenAI 兼容格式和 `max_completion_tokens`；其他 URL 保持 OpenAI 兼容的 `/v1/chat/completions`。
- Bot Chat：在 Dashboard 后端调用阿尔特塔对话/命令链路，返回文本 fallback 与 PNG data URL；前端优先显示与 QQ 群聊一致的渲染图片。支持上传最多 4 张图片（单张 ≤ 6 MB），后端复用 `plugins/arteta_vision.analyze_image_base64` 调用 SiliconFlow Qwen3-VL，主服务失败时 fallback 到备用 Vision 服务，识别结果以 `【用户发送的图片内容】` 形式拼入对话/算法 prompt 与记忆。Dashboard 与机器人主进程是两条独立的 uvicorn/NoneBot 进程，vision 调用走纯 `plugins.arteta_vision` 模块，避免在没有 NoneBot driver 的 Dashboard 进程里被 `plugins.arteta_chat` 顶层的 `on_command` 绊住。
- Prompt 人设：按功能分组管理机器人 prompt registry，可编辑主对话、Dashboard 对话、画像分析、每日总结、周报和算法/理科解题 prompt；进入页面后内置 key 的右侧文本框直接展示代码默认 prompt（不再是空白），方便对照修改。运行时仍以调用方传入的 `default` 参数为准——只有用户在 Dashboard 保存非空覆盖后，registry content 才会替换运行时 prompt；保存空字符串等同于"未覆盖"。只有内置 key 会被运行时调用，自定义 key 作为可保存文本资产。
- Group Profiles：查看群、用户、用户档案条目、昵称历史、最近消息和关系数据；群聊名称可在群聊列表右侧直接编辑；用户档案以"条目名称/条目内容"形式增删改，保存时仍写回原有 profile JSON 存储。**信任度调整**：右栏新增「信任度调整」区域，支持直接设值（含负值）和增减（正整数 ±）两种语义，提交后按统一阈值表（`<-50` 看台内鬼 / `<0` 预备队 / `<50` 青训生 / `<200` 一线队 / `<500` 核心首发 / `≥500` 传奇队长）刷新 `players.level`，并写入审计日志 `favor.set` / `favor.delta`；不存在的 player 行会自动以指定昵称插入。

## 安全规则

- Dashboard 要求管理员密码登录；面向局域网或服务器内网使用，不要直接公网暴露，公网使用时仍应通过安全组或反向代理限制来源。
- API Key 不会从后端返回明文。
- Group Profiles 可为单个群组设置或清除“群组访问密码”，状态会同步显示在 Chroma Memory 群组列表。
- 已设置群组访问密码的群组，用户列表、用户详情、档案保存和档案清空都必须先解锁。
- Chroma Memory 不提供“全部群组”入口；查看、搜索和删除记忆都必须选择具体群组。
- 已设置群组访问密码的群组，前端通过 `X-Group-Password` header 解锁列表/搜索/只读接口，通过写请求 body 传递密码；密码只保存在当前页面 state，不写入 localStorage。
- 群组访问密码用于 Dashboard 访问保护，不会加密已有 SQLite 数据、ChromaDB 文档或向量。
- Chroma 删除和 API Key 保存需要前端确认，并写入 `logs/dashboard_audit.log`；群组访问密码设置/清除同样写入审计日志。
- 设置 `DASHBOARD_READONLY=true` 可禁用 Chroma 删除、配置保存、用户档案写入和群组访问密码设置/清除。
- 文档、日志和 artifact 访问必须通过后端路径限制，不能任意读文件。

## 验证

后端测试：

```bash
python -m pytest tests/dashboard -v
```

机器人对话渲染测试：

```bash
python -m pytest tests/dashboard/test_bot_chat.py -v
npm --prefix dashboard/web run build
```

前端构建：

```bash
npm --prefix dashboard/web run build
```

项目核心验证：

```bash
python tools/verify_features.py --suite core
```

## Provider configuration (current)

This section supersedes the earlier legacy Config description. The Dashboard
now manages external credentials as complete provider groups rather than
individual environment fields. Each group is verified against its own provider
before it can be applied:

- Chat: `DEEPSEEK_*`; algorithm solving: `ALGO_*`; image generation:
  `IMAGE_*`; vision: `VISION_*`.
- Football data uses `FOOTBALL_API_TOKEN`; Grok Search uses
  `ARTETA_GROKSEARCH_*`; X Fetch uses `ARTETA_X_FETCH_*`.
- Chat and algorithm URLs are complete `/chat/completions` URLs. The other
  providers use base URLs, with the runtime transport adding its endpoint.

The Config page never returns or pre-fills an API key. The operator enters all
fields for one group, selects **Verify configuration**, and then selects
**Apply and restart bot** within five minutes. Editing any field invalidates
the receipt. A successful apply atomically replaces only that group in `.env`
and restarts `arteta_bot`; if the first restart fails, the Dashboard restores
the exact prior `.env` snapshot and attempts one recovery restart.

The former `/api/config/keys*` endpoints and global restart endpoint are
removed. Agent `update_config` calls also reject every provider-owned field, so
they cannot bypass verification, atomic persistence, or restart recovery.
Provider reads, validation, and apply all require a valid Dashboard admin
Bearer token obtained through the login page; unauthenticated requests are
rejected before provider data is read or a restart can be requested.
See [dashboard-provider-configuration.md](dashboard-provider-configuration.md)
for the endpoint contract, probe behaviour, and failure semantics.
