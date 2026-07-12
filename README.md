# Arteta Bot: 阿森纳 QQ 群聊 Agent

Arteta Bot 是一个基于 NoneBot2、OneBot V11 和 NapCat 的 QQ 群聊机器人，以阿森纳主教练米克尔·阿尔特塔的口吻参与群聊。项目已经从早期的单体工具循环升级为模块化 Agent 架构，当前重点是：真实群聊上下文、多意图工具规划、当前足球事实联网核验、权限确认、行为策略、审计追踪和可回滚 ECS 部署。

## 核心能力

- **群聊人格对话**：结合阿森纳、足球语境、群成员上下文、好感度和本地记忆生成回复。
- **当前足球事实联网**：阵容、伤病、转会、赛程、积分榜、最近比赛和近期状态等时效性问题会进入 Freshness Policy，必要时强制走 Web 工具，不再依赖模型旧知识猜测。
- **多意图工具规划**：同一条消息可以组合记忆、文档、链接、联网、渲染、策略修改等多个意图。
- **统一 Runtime**：强制工具、required tools、模型 tool calls 和后续 tool calls 走同一条执行路径。
- **权限分级工具系统**：工具按 `safe_read`、`safe_write`、`confirm_write`、`admin_action` 分级，写操作和管理操作必须由服务端确认。
- **结构化工具结果**：工具通过 `ToolResult` 返回状态、错误码、artifact、pending action、耗时和脱敏 trace。
- **行为策略持久化**：回复偏好、表情、工具禁用、UI 偏好等策略由 SQLite-backed Behavior Policy 管理，支持 TTL。
- **多媒体与渲染**：支持图片识别、AI 图片生成、HTML/Markdown 图片渲染、理科解题渲染和引用图处理。
- **群数据与长期记忆**：保留好感度、成员档案、昵称、群消息、每日总结、周报和 ChromaDB 向量记忆。

## 当前 Agent 架构

QQ 消息仍由 `plugins/arteta_chat.py` 接收。启用 Agent Registry 链路后，请求进入 `plugins/arteta_agent` 的分层架构：

```text
QQ 消息 / 命令
  -> plugins/arteta_chat.py
  -> plugins/arteta_agent/planner.py        # 兼容入口 run_agent_loop
  -> plugins/arteta_agent/service.py        # AgentRequest 编排
  -> routing/                               # Intent / RouteDecision / FreshnessDecision
  -> planning/                              # AgentPlan / required tools / dependencies
  -> runtime/                               # AgentState / LoopGuard / unified loop
  -> registry.py + executor.py              # ToolSpec / Schema / permission / handler
  -> providers/                             # OpenAI-compatible provider / shared HTTP client
  -> response/                              # final text / artifacts / trace / mood
```

### 数据流

```text
用户消息
  -> Activation 判断是否需要回复
  -> Routing 识别意图、上下文、时效性和可用工具
  -> Planning 生成 required tools、依赖关系和运行约束
  -> Runtime 执行工具、调用模型、处理预算和终止条件
  -> Executor 做参数校验、权限判断、PendingAction 和审计
  -> Provider 调用 OpenAI-compatible / DeepSeek 类模型
  -> Response Composer 组合最终文本、artifact、trace 和表情后处理
```

### 分层职责

| 层 | 主要位置 | 职责 |
| --- | --- | --- |
| Compatibility | `plugins/arteta_agent/planner.py` | 保留 `run_agent_loop(...)` 兼容入口，委托到新 Agent Service。 |
| Service | `plugins/arteta_agent/service.py` | 构造请求，串联 Routing、Planning、Runtime、Policy 和 Response。 |
| Routing | `plugins/arteta_agent/routing/` | 生成 `RouteDecision`，识别多意图、上下文工具、排除工具和足球时效性。 |
| Freshness | `plugins/arteta_agent/routing/freshness.py` | 判断足球问题是否需要当前信息，输出 `none`、`optional`、`required`。 |
| Planning | `plugins/arteta_agent/planning/` | 将路由结果转成 `AgentPlan`，支持 required tools 和显式依赖。 |
| Runtime | `plugins/arteta_agent/runtime/` | 统一执行工具和模型循环，处理预算、LoopGuard、确认等待、只读并行和当前信息失败降级。 |
| Provider | `plugins/arteta_agent/providers/` | 负责请求编码、响应解析、能力标记、重试、tool history 降级和共享 `httpx.AsyncClient`。 |
| Registry / Executor | `registry.py` / `executor.py` | 注册 `ToolSpec`，执行 JSON Schema 校验、权限检查、PendingAction 和 handler 调用。 |
| Response | `plugins/arteta_agent/response/` | 生成最终回复，处理 structured artifacts、trace 展示和 mood emoji，不执行工具。 |
| Policy | `behavior_policy.py` / `policy/` | 管理 SQLite 行为策略、TTL 消耗和 JSON 迁移兼容。 |
| Web Access | `plugins/arteta_agent/tools/web/` | 搜索、网页抓取、X/Twitter 读取、SSRF 校验、响应限制和事实证据收集。 |
| Audit | `plugins/arteta_agent/audit.py` | 持久化确认、拒绝、执行、异常、超时和管理动作的脱敏审计记录。 |

## 当前足球事实链路

真实群聊里很多问题不会显式说“搜索”，例如“萨卡怎么没上”“下一场打谁”“这笔转会成了吗”。这类问题现在由 Freshness Policy 处理：

```text
足球语境消息
  -> FreshnessDecision(mode="required")
  -> Planning 生成必需 Web 工具步骤
  -> Runtime 执行 GrokSearch / web_search / web_fetch / fetch_x_post
  -> 成功：基于当前工具观察回答
  -> 失败：明确无法核实，不使用旧知识兜底
```

稳定历史、规则和通用战术问题不会默认强制联网，例如“温格为什么离开阿森纳”“高位逼抢为什么怕长传”“2006 年欧冠决赛发生了什么”。

## 安全边界

- 动态外部内容不进入 `system` 消息：网页、PDF、附件、群消息、工具结果和异常文本都作为 tool/user 数据处理。
- 工具参数在 handler 前完成服务端 Schema 校验：缺字段、类型错误、额外字段、非法 enum、超长字符串/数组、非法 JSON 都会被拒绝。
- 权限状态不能由模型文本伪造：授权、确认、管理员校验、artifact 生成状态都只能由服务端结构化对象产生。
- `PendingAction` 绑定 action id、用户、群、工具和原始参数，并且只能原子消费一次。
- 只有显式 `parallel_safe=True`、权限为 `safe_read`、无依赖、无共享可变状态的工具才允许受限并行；写和管理工具始终串行。
- Provider 不支持标准 tool history 时，降级路径也不会把工具结果放入 `system`，并会保留 untrusted-data 边界。
- Web Access 做应用层 SSRF 防护：限制 scheme、端口、URL credentials、重定向、DNS 解析结果、Content-Type 和响应大小；生产环境仍依赖 egress 规则兜底。
- 审计记录保存结构化脱敏信息，不记录 API Key、Cookie、完整提示词、完整网页/PDF/群消息正文。

## 主要目录

```text
arteta_bot/
├── bot.py                         # NoneBot 启动入口和 loguru 日志配置
├── plugins/
│   ├── arteta_chat.py             # QQ 主对话入口、好感度和渲染路由
│   ├── arteta_agent/              # 当前 Agent 架构
│   │   ├── routing/               # Intent、RouteDecision、FreshnessDecision
│   │   ├── planning/              # AgentPlan、required tools、dependencies
│   │   ├── runtime/               # AgentState、LoopGuard、统一执行循环
│   │   ├── providers/             # LLM Provider Adapter 和共享 HTTP client
│   │   ├── response/              # 回复、artifact、trace、mood
│   │   ├── policy/                # 行为策略服务
│   │   └── tools/                 # Web、记忆、文档、QQ、管理、渲染等工具
│   ├── arteta_memory.py           # ChromaDB 群记忆
│   ├── arteta_vision.py           # 图片识别调用层
│   ├── arteta_image.py            # 图片生成
│   ├── arteta_render.py           # HTML/PIL 渲染
│   └── ...                        # 好感度、周报、积分榜、誓言等传统插件
├── dashboard/                     # 开发者 Dashboard / API
├── docs/                          # 用户、开发、运维和任务文档
├── tools/verify_features.py       # 本地功能验证入口
├── tools/evaluate_football_freshness.py
├── tools/groksearch_http_bridge.py
└── deploy/                        # ECS/Docker 部署脚本
```

## 快速开始

线上目标环境为 Python 3.8，开发时也必须保持 Python 3.8 兼容写法。

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
copy .env.dev .env
python bot.py
```

关键配置项：

| 配置 | 用途 |
| --- | --- |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` / `DEEPSEEK_API_URL` | 主对话 OpenAI-compatible 模型配置。 |
| `ARTETA_USE_AGENT_REGISTRY` | 是否启用新 Agent Registry 链路。 |
| `ARTETA_GROKSEARCH_API_URL` / `ARTETA_GROKSEARCH_API_KEY` | GrokSearch HTTP 桥配置。 |
| `ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH` | 行为策略 SQLite 数据库路径。 |
| `IMAGE_API_KEY` / `IMAGE_API_URL` / `IMAGE_MODEL` | 图片生成配置。 |
| `VISION_API_KEY` / `VISION_API_URL` / `VISION_MODEL` / `VISION_TIMEOUT` | 图片识别配置。 |

完整部署流程见 [docs/ops/deployment.md](docs/ops/deployment.md)。

## 常用指令

- `A/塔子/阿尔特塔 [内容]`：AI 对话。
- `算法 [题目]`：理科解题与渲染。
- `画图 [描述]`：AI 图片生成。
- `好感度` / `档案` / `盒`：成员档案和好感度。
- `赞我`：QQ 名片赞。
- `发誓 [目标]`：誓言系统。
- `帮助`：帮助菜单。

完整指令见 [docs/user/commands.md](docs/user/commands.md)。

## 验证

常用本地验证入口：

```bash
python tools/verify_features.py --suite chat --suite agent_loop --suite agent_registry --suite agent_permissions
python tools/evaluate_football_freshness.py --output artifacts/football_freshness_eval_report.json
python -m pytest tests/test_arteta_agent_registry.py -q
python -m pytest tests -q
python -m compileall -q bot.py plugins tests tools dashboard
```

最近的 Agent 架构、Web Access 和足球时效性验收记录见 [docs/dev/agent-architecture-devlog.md](docs/dev/agent-architecture-devlog.md)。

## 文档导航

- [用户功能概览](docs/user/features.md)
- [完整指令表](docs/user/commands.md)
- [开发者架构概览](docs/dev/overview.md)
- [Agent 架构交接文档](docs/dev/agent-architecture-handover.md)
- [Agent 架构 devlog](docs/dev/agent-architecture-devlog.md)
- [开发者验证工具](docs/dev/developer-verification.md)
- [Dashboard 文档](docs/dev/developer-dashboard.md)
- [部署指南](docs/ops/deployment.md)
- [故障排查](docs/ops/troubleshooting.md)
- [足球时效性联网计划](docs/tasks/arteta_football_freshness_web_plan.md)

## 开发约束

- 保持 Python 3.8 兼容：使用 `Dict[str, X]`、`List[X]`、`Optional[X]` 等 typing 写法。
- 不要绕过 `ToolSpec`、Schema、权限、PendingAction、Audit 或 Runtime。
- 不要把外部网页、PDF、附件、群消息或工具结果拼入动态 `system` 消息。
- 不要在 `planner.py` 里重新堆强制路由分支；Routing、Planning、Runtime、Response 各司其职。
- 修改后运行相关验证，更新必要文档。
- 每次更新完成后创建聚焦 commit，并推送到 `https://github.com/feiniao87968492/Arteta-bot.git`。

## 项目状态

项目处于活跃开发和线上运行状态。当前主线已经完成 Agent 架构重构，并补上当前足球事实主动联网链路；后续重点是继续用真实群聊评测集校准时效性路由，同时保持安全边界、测试覆盖和 ECS 部署可回滚性。
