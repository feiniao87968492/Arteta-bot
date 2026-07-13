# Arteta Bot

Arteta Bot 是一个基于 NoneBot2、OneBot V11 和 NapCat 的 QQ 群聊机器人。它以阿森纳主教练米克尔·阿尔特塔的口吻参与群聊，同时具备群记忆、实时足球信息核验、图片识别、图片生成、渲染、权限确认、行为策略和审计能力。

项目当前已经从早期的单体 `run_tool_loop()` 演进为模块化 Agent 架构：`planner.py` 只保留 `run_agent_loop(...)` 兼容入口，并把旧参数封装成 `AgentRequest`；真正的决策、计划、运行、工具执行、模型调用、回复生成和策略持久化分别由独立模块负责。

## 核心能力

- **阿尔特塔人格群聊**：结合阿森纳语境、群成员档案、好感度、本地记忆和近期上下文生成回复。
- **当前足球事实核验**：阵容、伤病、转会、赛程、积分榜、最近比赛和实时状态会进入 Freshness Policy；需要当前事实时强制走 Web/GrokSearch，不用模型旧知识兜底。
- **多意图工具计划**：一条消息可以同时触发记忆、文档、链接、联网、渲染、策略更新、QQ 动作等多个意图。
- **统一 Runtime**：强制工具、required tools、模型 tool calls 和工具后的后续 tool calls 都走同一条执行链路。
- **服务端权限边界**：工具按 `safe_read`、`safe_write`、`confirm_write`、`admin_action` 分级；写操作和管理操作必须经过服务端 PendingAction 确认。
- **结构化工具结果**：工具通过 `ToolResult` 返回状态、错误码、artifact、pending action、耗时和脱敏 trace，不依赖正文伪造控制标记。
- **SQLite 行为策略**：回复风格、表情、工具禁用、UI 偏好等由 Behavior Policy 持久化，支持 TTL、迁移和并发安全更新。
- **Provider Adapter**：兼容 DeepSeek 和 OpenAI-compatible API，Provider 层负责能力标记、重试、reasoning content、tool history 降级和共享 HTTP client。
- **Web Access 安全收口**：搜索、网页抓取、X/Twitter 读取和事实证据收集已拆分模块，并带 SSRF best-effort 校验、重定向校验、Content-Type 与响应大小限制。
- **多媒体能力**：支持图片识别、AI 图片生成、HTML/Markdown 图片渲染、理科解题渲染和引用图片处理。
- **群数据与长期记忆**：SQLite 保存成员、昵称、好感度、群消息、每日总结、周报等结构化数据；ChromaDB 保存向量记忆和足球新闻向量库。

## 最新 Agent 架构

```text
QQ / NapCat
  -> NoneBot2
  -> plugins/arteta_chat.py
  -> plugins/arteta_agent/planner.py        # 兼容入口 run_agent_loop(...)
  -> AgentRequest
  -> plugins/arteta_agent/service.py        # 请求准备、确认消费、策略 TTL 和最终组合
  -> activation.py                          # 群聊自主唤醒 cheap gate + LLM gate
  -> routing/                               # Intent / RouteDecision / FreshnessDecision
  -> planning/                              # AgentPlan / required tools / explicit dependencies
  -> runtime/                               # AgentState / LoopGuard / unified execution loop
  -> registry.py + executor.py              # ToolSpec / Schema / permission / handler
  -> providers/                             # OpenAI-compatible provider / shared HTTP client
  -> response/                              # final text / artifacts / trace / mood
```

### 主请求数据流

```text
用户消息
  -> Activation 判断是否需要回复
  -> Routing 识别意图、上下文、时效性和可用工具
  -> Planning 生成 required tools、依赖关系和运行约束
  -> Runtime 执行计划、调用模型、处理预算和终止条件
  -> Executor 做参数校验、权限判断、PendingAction 和审计
  -> Tools / Provider 读取外部信息或调用模型
  -> Response Composer 组合最终文本、artifact、trace 和表情后处理
  -> arteta_chat.py 继续处理好感度、记忆写入和渲染发送
```

### 分层职责

| 层 | 主要位置 | 职责 |
| --- | --- | --- |
| Compatibility | `plugins/arteta_agent/planner.py` | 保留 `run_agent_loop(...)` 外部调用兼容，委托到 Agent Service。 |
| Service | `plugins/arteta_agent/service.py` | 构造请求，串联 routing、planning、runtime、policy 和 response。 |
| Activation | `plugins/arteta_agent/activation.py` | 群聊场景下判断是否需要唤醒主 Agent，避免普通闲聊触发慢模型。 |
| Routing | `plugins/arteta_agent/routing/` | 输出 `RouteDecision`，识别多意图、上下文工具、排除工具和足球时效性。 |
| Freshness | `plugins/arteta_agent/routing/freshness.py` | 判断足球问题是否需要当前信息，输出 `none`、`optional`、`required`。 |
| Planning | `plugins/arteta_agent/planning/` | 将路由结果转成 `AgentPlan`，支持 required tools 和显式依赖关系。 |
| Runtime | `plugins/arteta_agent/runtime/` | 统一执行工具和模型循环，处理预算、LoopGuard、确认等待、只读并行和降级。 |
| Registry / Executor | `plugins/arteta_agent/registry.py` / `executor.py` | 注册 `ToolSpec`，执行 JSON Schema 校验、权限检查、PendingAction 和 handler 调用。 |
| Provider | `plugins/arteta_agent/providers/` | 负责 LLM 请求编码、响应解析、能力标记、重试、tool history 降级和共享 `httpx.AsyncClient`。 |
| Response | `plugins/arteta_agent/response/` | 生成最终回复，处理 structured artifacts、trace 展示和 mood emoji，不执行工具。 |
| Policy | `plugins/arteta_agent/behavior_policy.py` / `policy/` | 管理 SQLite 行为策略、TTL 消耗和旧 JSON 迁移兼容。 |
| Web Access | `plugins/arteta_agent/tools/web/` | 搜索、网页抓取、X/Twitter 读取、SSRF 校验、响应限制、格式化和事实证据收集。 |
| Audit | `plugins/arteta_agent/audit.py` | 持久化确认、拒绝、执行、异常、超时和管理动作的脱敏审计记录。 |

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

## 当前足球事实链路

真实群聊里的足球问题经常不会直接说“搜索”，例如：

```text
萨卡怎么没上？
下一场打谁？
这笔转会成了吗？
塔子你了解西班牙和比利时最近一场比赛吗？
```

这类问题会进入 Freshness Policy：

```text
足球语境消息
  -> FreshnessDecision(mode="required")
  -> Planning 生成必需 Web 工具步骤
  -> Runtime 执行 grok_search / web_search / web_fetch / fetch_x_post
  -> 成功：基于当前工具观察回答
  -> 失败：明确说明无法核实，不使用旧知识兜底
```

稳定历史、规则和通用战术问题不会默认强制联网，例如“温格为什么离开阿森纳”“高位逼抢为什么怕长传”“2006 年欧冠决赛发生了什么”。

## 工具体系

| 类别 | 代表工具 | 说明 |
| --- | --- | --- |
| 足球数据 | `get_arsenal_result`、`get_pl_table`、`get_arsenal_injuries` | 比赛结果、积分榜、伤病等结构化足球信息。 |
| Web / Research | `grok_search`、`web_search`、`web_fetch`、`fetch_x_post`、`verify_recent_claim` | 当前事实、网页、X/Twitter 和候选证据收集。 |
| 记忆与群上下文 | `query_group_memory`、`get_recent_group_context`、`remember_user_preference` | 群记忆、近期上下文和偏好写入。 |
| 文档与链接 | `read_document`、`analyze_link` | 附件、PDF、网页链接与引用内容分析。 |
| 渲染与多媒体 | `render_html`、`generate_image`、vision 调用层 | 图片生成、图片识别和 HTML/Markdown 渲染。 |
| 行为策略 | `show_behavior_policy`、`update_behavior_policy` | 查看和修改带 TTL 的行为策略。 |
| QQ / 管理动作 | 发送、撤回、禁言、档案修改等工具 | 受 `confirm_write` 或 `admin_action` 权限保护。 |

## 安全边界

- 外部动态内容不进入 `system` 消息：网页、PDF、附件、群消息、工具结果和异常文本都只作为 tool/user 数据处理。
- 工具参数必须在 handler 前完成服务端 Schema 校验：缺字段、类型错误、额外字段、非法 enum、超长字符串/数组、非法 JSON 都会被拒绝。
- 权限状态不能由模型文本伪造：授权、确认、管理员校验和 artifact 生成状态只能由服务端结构化对象产生。
- `PendingAction` 绑定 action id、用户、群、工具和原始参数，并且只能在数据库事务中原子消费一次。
- 只有显式 `parallel_safe=True`、权限为 `safe_read`、无依赖、无共享可变状态的工具才允许受限并行；写和管理工具始终串行。
- Provider 不支持标准 tool history 时，降级路径也不会把工具结果放入 `system`，并保留 untrusted-data 包络。
- Web Access 做应用层 SSRF best-effort 防护：限制 scheme、端口、URL credentials、重定向、DNS 解析结果、Content-Type 和响应大小；生产环境仍需要 egress 规则兜底。
- 审计记录只保存结构化脱敏信息，不记录 API Key、Cookie、完整提示词、完整网页/PDF/群消息正文。

## 主要目录

```text
arteta_bot/
├── bot.py                         # NoneBot 启动入口和 loguru 日志配置
├── plugins/
│   ├── arteta_chat.py             # QQ 主对话入口、好感度、记忆写入和渲染发送
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
├── Docs/                          # 用户、开发、运维和任务文档
├── tools/verify_features.py       # 本地功能验证入口
├── tools/evaluate_football_freshness.py
├── tools/groksearch_http_bridge.py
└── deploy/                        # ECS/Docker 部署脚本
```

## 快速开始

线上目标环境是 Python 3.8，开发时也必须保持 Python 3.8 兼容写法。

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

完整部署流程见 [Docs/ops/deployment.md](Docs/ops/deployment.md)。

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
python tools/verify_features.py --suite chat --suite agent_loop --suite agent_registry --suite agent_permissions
python tools/evaluate_football_freshness.py --output artifacts/football_freshness_eval_report.json
python -m pytest tests/test_arteta_agent_registry.py -q
python -m pytest tests -q
python -m compileall -q bot.py plugins tests tools dashboard
```

最近的 Agent 架构、Web Access 和足球时效性验收记录见 [Docs/dev/agent-architecture-devlog.md](Docs/dev/agent-architecture-devlog.md)。

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
- [足球时效性联网计划](Docs/tasks/arteta_football_freshness_web_plan.md)
- [Web Access 改造计划](Docs/tasks/rebulid_webaccess.md)

## 开发约束

- 保持 Python 3.8 兼容：使用 `Dict[str, X]`、`List[X]`、`Optional[X]` 等 typing 写法。
- 新增或修改功能前做发散检查，但最终实现保持可控、可回滚、可验证。
- 不要绕过 `ToolSpec`、Schema、权限、PendingAction、Audit 或 Runtime。
- 不要把外部网页、PDF、附件、群消息或工具结果拼入动态 `system` 消息。
- 不要在 `planner.py` 里重新堆强制路由分支；Routing、Planning、Runtime、Response 各司其职。
- 修改后运行相关验证，更新必要文档。
- 每次更新完成后创建聚焦 commit，并推送到 `https://github.com/feiniao87968492/Arteta-bot.git`。

## 项目状态

项目处于活跃开发和线上运行状态。当前主线已经完成 Agent 架构重构、Web Access 安全收口和当前足球事实主动联网链路；后续重点是继续用真实群聊评测集校准时效性路由，并保持安全边界、测试覆盖、GitHub 提交纪律和 ECS 部署可回滚性。
