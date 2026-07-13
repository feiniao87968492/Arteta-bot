# Arteta Bot — 阿森纳 QQ 群聊 Agent

Arteta Bot 是一个基于 NoneBot2 + OneBot V11 / NapCat 的 QQ 群聊机器人，以阿森纳主教练米克尔·阿尔特塔的口吻参与群聊。项目已经从早期的单体工具循环升级为模块化 Agent 架构：`planner.py` 只保留 `run_agent_loop(...)` 兼容入口，并把旧参数封装成 `AgentRequest`；Routing、Planning、Runtime、Provider、Response、Policy 和工具执行层分别负责自己的边界。

## 核心能力

- **群聊人格对话**：围绕阿森纳、足球、群成员上下文和本地记忆生成回复。
- **实时信息核验**：通过 GrokSearch、Bing/DuckDuckGo/Jina 后备链、网页抓取、X/Twitter 读取和 `verify_recent_claim` 进行当前事实查询。
- **多意图工具规划**：同一条消息可以组合记忆、文档、链接、联网、渲染、策略等多个工具意图。
- **权限分级工具系统**：工具按 `safe_read`、`safe_write`、`confirm_write`、`admin_action` 分级，写操作和管理操作必须经服务端确认。
- **结构化工具结果**：工具返回 `ToolResult`，包含状态、错误码、artifact、pending action、耗时和脱敏 trace 信息。
- **行为策略持久化**：表情、工具禁用、回复偏好、UI 偏好等行为策略通过 SQLite/兼容层管理，支持 TTL。
- **多媒体与渲染**：支持 AI 图片生成、图片识别、HTML/Markdown 图片渲染、理科解题渲染和引用图处理。
- **好感度与群数据**：保留原有好感度、成员档案、昵称、群消息、每日总结、周报和 ChromaDB 向量记忆能力。

## 最新 Agent 架构

主对话入口仍由 `plugins/arteta_chat.py` 接收 QQ 消息；当启用 Agent Registry 链路时，请求进入 `plugins/arteta_agent` 的分层架构：

```text
QQ 消息 / 命令
  -> plugins/arteta_chat.py
  -> plugins/arteta_agent/planner.py        # 兼容入口 run_agent_loop
  -> AgentRequest
  -> plugins/arteta_agent/service.py        # 请求准备、确认消费、策略 TTL 和最终组合
  -> routing/                               # RouteDecision / Intent / 初步工具约束
  -> planning/                              # AgentPlan / required tools / explicit dependencies
  -> runtime/                               # AgentState / LoopGuard / 统一执行循环
  -> registry.py + executor.py              # ToolSpec / Schema / 权限 / handler
  -> providers/                             # OpenAI-compatible provider / shared HTTP client
  -> tools/                                 # Web、记忆、文档、QQ、管理、渲染等工具
  -> response/                              # 最终文本、artifact、trace、mood 后处理
```

### 分层职责

| 层 | 主要文件 | 职责 |
| --- | --- | --- |
| Compatibility | `planner.py` | 保留 `run_agent_loop` 外部入口，委托到新 Agent Service。 |
| Service | `service.py` | 构造 AgentRequest，串联路由、计划、运行时、策略和响应。 |
| Routing | `routing/` | 生成 `RouteDecision`，识别多意图、工具排除、上下文工具暴露。 |
| Planning | `planning/` | 将路由结果转为 `AgentPlan`，支持 required tools 和显式依赖关系。 |
| Runtime | `runtime/` | 统一执行强制工具、计划工具和模型 tool calls；处理预算、循环保护、确认等待、并行只读工具。 |
| Provider | `providers/` | OpenAI-compatible/DeepSeek 兼容调用、能力标记、重试、tool history 降级和共享 HTTP client。 |
| Registry | `registry.py` / `executor.py` | 注册 ToolSpec、执行 JSON Schema 校验、权限检查、PendingAction 和 handler 调用。 |
| Response | `response/` | 组合最终回复、artifact、trace 展示和表情后处理，不执行工具。 |
| Policy | `policy/` / `behavior_policy.py` | 行为策略读取、TTL 消耗、SQLite 存储和 JSON 迁移兼容。 |
| Web Access | `tools/web/` | URL/SSRF 校验、响应大小/类型限制、搜索后端、网页抓取、X 来源标注和事实证据收集。 |

### 关键结构化对象

| 对象 | 位置 | 用途 |
| --- | --- | --- |
| `AgentRequest` | `plugins/arteta_agent/service.py` | `planner.py` 的兼容参数被封装成请求对象，供 Service 统一调度。 |
| `RouteDecision` / `Intent` | `plugins/arteta_agent/routing/models.py` | 表达多意图、工具约束、上下文排除和足球时效性判断。 |
| `AgentPlan` | `plugins/arteta_agent/planning/models.py` | 保存 required tools、excluded tools、constraints 和显式依赖关系。 |
| `AgentState` | `plugins/arteta_agent/runtime/state.py` | 记录运行中消息、工具结果、预算、当前事实状态和停止原因。 |
| `ToolSpec` | `plugins/arteta_agent/registry.py` | 定义工具 schema、权限等级、幂等性、并发安全能力和 handler。 |
| `ToolResult` | `plugins/arteta_agent/result.py` | 结构化承载工具状态、错误码、artifact、marker、pending action 和耗时。 |
| `ProviderCapabilities` | `plugins/arteta_agent/providers/openai_compatible.py` | 声明模型供应商是否支持 tool history、JSON schema、reasoning content 等能力。 |

## 安全边界

- **动态外部内容不进入 system 消息**：网页、PDF、群消息、工具结果和异常文本都作为 tool/user 数据处理。
- **工具参数先校验再执行**：缺字段、类型错误、额外字段、非法 enum、超长字符串/数组和非法 JSON 会在 handler 前被拒绝。
- **权限由服务端强制**：模型文本不能声明已授权、已确认、已通过管理员校验或已生成可信 artifact。
- **PendingAction 原子消费**：确认写操作绑定 action id、用户、群、工具和原始参数，只能消费一次。
- **受限并行**：只有显式 `parallel_safe=True`、`safe_read`、无依赖、无共享状态的工具才会并行；写和管理工具始终串行。
- **Web SSRF 防护**：限制 scheme、端口、URL credentials、重定向、DNS 解析结果、Content-Type 和响应大小；生产环境仍需要 egress 防火墙兜底。
- **审计与脱敏**：确认请求、执行、拒绝、异常、超时和管理动作持久化审计，避免记录 API Key、Cookie、完整网页/PDF/群消息内容。

## 主要目录

```text
arteta_bot/
├── bot.py                         # NoneBot 启动入口和 loguru 日志配置
├── plugins/
│   ├── arteta_chat.py             # QQ 主对话入口、好感度和渲染路由
│   ├── arteta_agent/              # 最新 Agent 架构
│   │   ├── routing/               # 路由与多意图判断
│   │   ├── planning/              # 工具计划与依赖
│   │   ├── runtime/               # 统一 Runtime 和 AgentState
│   │   ├── providers/             # LLM Provider Adapter
│   │   ├── response/              # 回复、artifact、trace、mood
│   │   ├── policy/                # 行为策略服务
│   │   └── tools/                 # Agent 工具集合
│   ├── arteta_memory.py           # ChromaDB 群记忆
│   ├── arteta_vision.py           # 图片识别调用层
│   ├── arteta_image.py            # 图片生成
│   ├── arteta_render.py           # HTML/PIL 渲染
│   └── ...                        # 好感度、周报、积分榜、誓言等传统插件
├── dashboard/                     # 开发者 Dashboard / API
├── Docs/                          # 用户、开发、运维文档
├── tools/verify_features.py       # 本地功能验证入口
├── tools/groksearch_http_bridge.py# GrokSearch HTTP 桥
└── deploy/                        # ECS/Docker 部署脚本
```

## 快速开始

项目线上目标环境为 Python 3.8，开发时也应保持 Python 3.8 兼容写法。

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
copy .env.dev .env
python bot.py
```

关键配置项包括：

| 配置 | 用途 |
| --- | --- |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` / `DEEPSEEK_API_URL` | 主对话 OpenAI-compatible 模型配置。 |
| `ARTETA_USE_AGENT_REGISTRY` | 是否启用新 Agent Registry 链路。 |
| `ARTETA_GROKSEARCH_API_URL` / `ARTETA_GROKSEARCH_API_KEY` | GrokSearch HTTP 桥配置。 |
| `ARTETA_AGENT_BEHAVIOR_POLICY_DB_PATH` | 行为策略 SQLite 数据库路径。 |
| `IMAGE_API_KEY` / `IMAGE_API_URL` / `IMAGE_MODEL` | 图片生成配置。 |
| `VISION_API_KEY` / `VISION_API_URL` / `VISION_MODEL` / `VISION_TIMEOUT` | 图片识别配置。 |

完整配置和部署步骤见 [Docs/ops/deployment.md](Docs/ops/deployment.md)。

## 常用指令

- `A/塔子/阿尔特塔 [内容]`：AI 对话。
- `算法 [题目]`：理科解题与渲染。
- `画图 [描述]`：AI 图片生成。
- `好感度` / `档案` / `盒`：成员档案和好感度。
- `赞我`：QQ 名片赞。
- `发誓 [目标]`：誓言系统。
- `帮助`：帮助菜单。

完整指令见 [Docs/user/commands.md](Docs/user/commands.md)。

## 验证

常用本地验证入口：

```bash
python tools/verify_features.py --suite chat --suite agent_registry --suite agent_permissions --suite agent_loop
python -m pytest tests/test_arteta_agent_registry.py -q
python -m pytest tests -q
python -m compileall -q plugins tests tools dashboard
```

Web Access 和 Agent 架构的最近验收记录见 [Docs/dev/agent-architecture-devlog.md](Docs/dev/agent-architecture-devlog.md)。

## 文档导航

- [用户功能概览](Docs/user/features.md)
- [完整指令表](Docs/user/commands.md)
- [开发者架构概览](Docs/dev/overview.md)
- [Agent 架构交接文档](Docs/dev/agent-architecture-handover.md)
- [Agent 架构 devlog](Docs/dev/agent-architecture-devlog.md)
- [开发者验证工具](Docs/dev/developer-verification.md)
- [Dashboard 文档](Docs/dev/developer-dashboard.md)
- [部署指南](Docs/ops/deployment.md)
- [故障排查](Docs/ops/troubleshooting.md)

## 开发约束

- 保持 Python 3.8 兼容：使用 `Dict[str, X]`、`List[X]`、`Optional[X]` 等 typing 写法。
- 不要绕过 `ToolSpec`、Schema、权限、PendingAction、Audit 或 Runtime。
- 每次修改后运行相关验证，更新必要文档。
- 每次更新完成后创建聚焦 commit，并推送到 `https://github.com/feiniao87968492/Arteta-bot.git`。

## 项目状态

项目处于活跃开发和线上运行状态。当前重点是保持 Agent 架构的可测试性、安全边界和 ECS 部署可回滚性。
