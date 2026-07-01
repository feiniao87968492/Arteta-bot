# DeepSeek Model Config and ECS Rollout Design

## Goal
将 Arteta Bot 项目中当前写死为 `deepseek-v4-flash` 的 DeepSeek 主链路模型统一改为通过配置项 `DEEPSEEK_MODEL` 控制，并把默认值升级为 `deepseek-v4-pro`。同时让 Dashboard 配置页可查看/修改该项，并完成一次线上 ECS 部署。

## Scope
本次只处理现有 DeepSeek 主链路的模型来源统一化，不改变业务用途、调用方式和提示词结构。

覆盖范围：
- `plugins/arteta_chat.py`：主聊天链路中的 DeepSeek 调用、画像分析等当前写死模型的调用点
- `plugins/arteta_tools.py`：Function Calling 工具链路中的 DeepSeek 调用
- `plugins/arteta_daily.py`：每日总结
- `plugins/arteta_weekly.py`：周报生成
- `plugins/arteta_standings.py`：积分榜解读
- `dashboard/api/config.py` 及相关环境配置读取链路：将 `DEEPSEEK_MODEL` 纳入白名单与可展示配置
- `deploy/deploy_ecs.sh`：新增生产环境变量输出
- 相关开发/运维文档

明确不处理：
- `ALGO_MODEL` 对应的算法/技术问题专用链路
- `IMAGE_MODEL`、`VISION_MODEL` 及其调用逻辑
- prompt、temperature、max_tokens 等生成参数
- 与本次模型切换无关的重构

## Configuration Design
### 1. 新增统一配置项
新增环境变量/NoneBot 配置项：`DEEPSEEK_MODEL`。

默认值：`deepseek-v4-pro`

设计原则：
- 所有原本写死为 `deepseek-v4-flash` 的 DeepSeek 调用点统一读取该配置。
- 即使线上环境尚未写入该变量，代码也能凭默认值正常启动。
- 配置风格与现有 `ALGO_MODEL`、`IMAGE_MODEL`、`VISION_MODEL` 保持一致。

### 2. 插件读取方式
在直接读取 `nonebot.get_driver().config` 的插件中，增加：

```python
DEEPSEEK_MODEL = str(config.get("deepseek_model", "deepseek-v4-pro")).strip('"\'')
```

并将原有：

```python
"model": "deepseek-v4-flash"
```

替换为：

```python
"model": DEEPSEEK_MODEL
```

### 3. 工具初始化透传
`plugins/arteta_tools.py` 当前通过 `init_tools(...)` 注入配置。这里需要同时支持 `deepseek_model`，避免工具链路仍然隐式写死旧模型。

设计要求：
- 模块级新增 `DEEPSEEK_MODEL` 默认值。
- `init_tools(...)` 从 `kwargs` 接收 `deepseek_model`，未传入时回退到 `deepseek-v4-pro`。
- `call_deepseek_tool(...)` 内请求体统一使用该变量。

### 4. Dashboard 配置白名单
在 `dashboard/api/config.py` 的 `ENV_WHITELIST` 中加入 `DEEPSEEK_MODEL`。

结果：
- Dashboard Config 页面能显示该键。
- 因为它不是 secret/token 类字段，所以展示时应显示完整值而不是掩码。
- Dashboard 保存配置时可直接更新 `.env` / `.env.prod` 中的该项。

## Code Change Boundaries
### 1. 聊天主链路
`plugins/arteta_chat.py` 中至少有以下两类 DeepSeek 使用点需要统一：
- 主对话/画像分析调用
- 初始化 `arteta_tools` 时的配置透传

改动要求：
- 增加统一 `DEEPSEEK_MODEL` 常量。
- 保持现有 API URL、headers、消息结构、超时与错误处理不变。
- `init_tools(...)` 调用时显式传入 `deepseek_model=DEEPSEEK_MODEL`。

### 2. 其他定时/内容生成插件
在 `plugins/arteta_daily.py`、`plugins/arteta_weekly.py`、`plugins/arteta_standings.py` 中：
- 新增统一 `DEEPSEEK_MODEL` 常量。
- 将请求体中的模型字段切到该常量。
- 不改变这些模块其余逻辑。

### 3. 工具链路
`plugins/arteta_tools.py` 中：
- 增加 `DEEPSEEK_MODEL` 全局配置。
- 在 `init_tools(...)` 中初始化。
- 在 `call_deepseek_tool(...)` 中使用。

## Deployment Design
### 1. ECS 配置文件生成
更新 `deploy/deploy_ecs.sh`：
- 在脚本顶部增加 `DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-pro}"`
- 在生成 `.env.prod` 的区块中写入：
  - `DEEPSEEK_MODEL=${DEEPSEEK_MODEL}`

这样新部署环境与现有环境都拥有一致的配置语义。

### 2. 上线时的最小变更原则
本次线上部署不直接粗暴覆盖线上完整配置文件，而是遵循：
1. SSH 登录 ECS 检查当前目录与 Supervisor 状态。
2. 备份线上关键配置（至少 `.env.prod`，必要时检查 `.env` 与 Supervisor 配置）。
3. 上传本次修改涉及的代码与文档文件。
4. 在线上配置中确保 `DEEPSEEK_MODEL=deepseek-v4-pro` 存在。
5. 重启 `arteta_bot`；若 Dashboard 配置接口读取白名单变更需要生效，则一并重启 `arteta_dashboard`。
6. 查看日志确认无缺失配置或启动错误。

### 3. 线上验证
部署完成后至少执行：
- `supervisorctl status arteta_bot`
- `supervisorctl status arteta_dashboard`（如果该进程存在且本次涉及重启）
- 查看 bot 日志中是否有启动错误
- 如环境允许，进行一次最小 smoke test，确认主聊天链路可用

## Testing Strategy
### 1. 静态覆盖检查
确认项目内所有当前 `deepseek-v4-flash` 字面量调用点都被替换为 `DEEPSEEK_MODEL` 或等价统一变量，不保留遗漏分叉。

### 2. 最小测试补强
根据现有测试分布，优先补或更新以下测试：
- Dashboard 配置白名单测试：断言 `DEEPSEEK_MODEL` 在 `ENV_WHITELIST` 中。
- 如已有环境服务测试，补充 `DEEPSEEK_MODEL` 的显示/保存行为验证。
- 如现有插件测试涉及模型名断言，则同步更新为读取变量后的预期。

### 3. 本地验证
在不依赖真实外部 API 的前提下，完成最小必要测试运行，重点验证：
- 代码可导入
- 配置默认值可用
- 现有测试未因新配置项破坏

## Documentation Updates
需要同步更新以下文档：
- `Docs/dev/overview.md`：把主 LLM 描述从写死模型名改为 `DEEPSEEK_MODEL` 控制，默认 `deepseek-v4-pro`
- `Docs/dev/chat-llm.md`：更新主聊天链路、画像分析、tool loop 中的模型说明
- `Docs/dev/daily-summary.md`：更新模型说明
- `Docs/dev/weekly-news.md`：更新模型说明
- `Docs/ops/deployment.md` 或相关部署文档：补充 `DEEPSEEK_MODEL`
- 如 Dashboard 配置文档列出了白名单变量，也要补上该项

文档更新原则：
- 说明“模型由配置控制”而不是继续写死具体实现
- 保留默认值信息，方便运维快速对照

## Risks and Mitigations
### 风险 1：线上配置漂移
线上 `.env.prod` 或 Dashboard 读取文件可能与仓库模板不同。

缓解：
- 先检查线上实际文件再修改。
- 避免整文件覆盖，优先做最小增量更新。

### 风险 2：工具链路遗漏
若只改聊天文件而未改 `arteta_tools.py`，Function Calling 仍可能继续使用旧模型。

缓解：
- 将 `arteta_tools.py` 明确纳入必改范围。
- 通过全仓搜索确认没有残留调用点。

### 风险 3：Dashboard 与 bot 配置来源不一致
Dashboard 可能显示新配置，但 bot 进程未读取到同一文件。

缓解：
- 核对 Supervisor 中 `DASHBOARD_ENV_FILE` 与 bot 实际读取的 `.env` / `.env.prod` 路径。
- 部署后同时检查 Dashboard 与 bot 进程状态。

## Success Criteria
满足以下条件视为完成：
1. 项目内所有现有 DeepSeek 主链路调用都改为读取统一的 `DEEPSEEK_MODEL`。
2. 默认值为 `deepseek-v4-pro`，缺少该变量时仍能正常启动。
3. Dashboard Config 页面后端白名单包含 `DEEPSEEK_MODEL`。
4. 部署脚本会写出 `DEEPSEEK_MODEL=deepseek-v4-pro`。
5. 本地最小验证通过。
6. ECS 上完成部署并确认相关进程启动正常。
