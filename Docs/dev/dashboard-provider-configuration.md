# Dashboard 服务组配置

## 破坏性变更

Dashboard 不再提供单字段配置写入或独立机器人重启接口：

- `POST /api/config/keys` 已移除。
- `GET /api/config/keys` 和 `GET /api/config/keys/{name}/test` 已移除。
- `POST /api/config/restart-bot` 已移除。

所有外部服务必须作为完整服务组验证并应用。不能通过 Agent 的
`update_config` 工具修改这些字段。

## 配置一个服务

在 Dashboard 的“服务配置”页面中，完成一张服务卡片的全部字段后，依次执行：

1. 点击 `Verify configuration`。Dashboard 使用当前表单中的候选值执行最小真实请求，不写入 `.env`。
2. 验证成功后，点击 `Apply and restart bot` 并确认。
3. Dashboard 原子更新该服务组的 `.env` 字段，并执行
   `supervisorctl restart arteta_bot`。

Key 永远不会回填到页面。即使该组已配置，再次应用时也必须重新输入完整 Key。
修改任一字段会使已有验证凭据失效。验证凭据仅对同一组、同一组值和同一
Dashboard 会话有效，五分钟后过期且只能使用一次。

## 服务组字段

| 服务组 | 字段 |
| --- | --- |
| 对话 | `DEEPSEEK_API_URL`、`DEEPSEEK_MODEL`、`DEEPSEEK_API_KEY`、`DEEPSEEK_TEMPERATURE` |
| 算法解题 | `ALGO_API_URL`、`ALGO_MODEL`、`ALGO_API_KEY` |
| 图片生成 | `IMAGE_API_URL`、`IMAGE_MODEL`、`IMAGE_API_KEY` |
| 图片识别 | `VISION_API_URL`、`VISION_MODEL`、`VISION_API_KEY`、`VISION_TIMEOUT` |
| 足球数据 | `FOOTBALL_API_TOKEN` |
| Grok 搜索 | `ARTETA_GROKSEARCH_API_URL`、`ARTETA_GROKSEARCH_MODEL`、`ARTETA_GROKSEARCH_API_KEY`、`ARTETA_GROKSEARCH_TIMEOUT` |
| X Fetch | `ARTETA_X_FETCH_API_URL`、`ARTETA_X_FETCH_API_KEY` |

对话和算法解题的 URL 必须是完整的 `/chat/completions` 地址。图片生成、图片识别、Grok 搜索和 X Fetch 使用服务基础 URL，由运行时按服务协议追加路径。

## 验证请求

验证仅检查候选组本身，不会借用其他服务组的 URL、模型或 Key。

| 服务组 | 验证方式 | 持久化副作用 |
| --- | --- | --- |
| 对话、算法解题 | 固定短提示的 `chat/completions` 请求，`max_tokens=1` | 无 |
| 图片生成 | 模型列表/能力探测，并检查返回模型列表中的目标模型 | 无图片生成 |
| 图片识别 | 内置 1x1 PNG 的 Vision 请求 | 无 |
| 足球数据 | 英超积分榜请求 | 无 |
| Grok 搜索 | 固定关键词、最多一条结果的检索 | 无持久化 |
| X Fetch | 固定公开 X URL 的 `/fetch` 请求，只校验 JSON 响应 | 无持久化 |

超时、401/403、模型不可用、错误 URL、响应结构错误或字段不完整都会阻止应用。
包含换行、回车或 NUL 的字段在网络请求前就会被拒绝。

## 应用失败时的行为

应用会先完整保存旧 `.env` 内容，再原子替换目标服务组字段。文件中的无关变量、注释和行尾注释都会保留。

若 `arteta_bot` 重启失败，Dashboard 会立即恢复保存前的 `.env`，然后再重启一次旧配置。页面会显示恢复是否成功；不会把 Supervisor 原始输出或服务密钥回传到浏览器。

图片识别只读取 `VISION_*`，算法解题只读取 `ALGO_*`。图片生成组和对话组不能再作为它们的凭据 fallback。SiliconFlow 仍是图片识别模块内部的应急 fallback，但不属于 Dashboard 可编辑服务组。

## API 调试

受 Dashboard 认证保护的 API：

```text
GET  /api/config/providers
POST /api/config/providers/{provider}/validate
POST /api/config/providers/{provider}/apply
```

`validate` 请求体：

```json
{
  "values": {
    "DEEPSEEK_API_URL": "https://provider.example/v1/chat/completions",
    "DEEPSEEK_MODEL": "example-model",
    "DEEPSEEK_API_KEY": "<key>",
    "DEEPSEEK_TEMPERATURE": "0.7"
  }
}
```

成功响应包含短期 `receipt`。`apply` 使用相同 `values` 和该 `receipt`：

```json
{
  "values": { "...": "same verified values" },
  "receipt": "<validation-receipt>"
}
```

不要把真实 Key 放入 shell 历史、日志、测试 fixture 或提交记录。

## 本地验证

```powershell
python -m pytest tests/dashboard/test_provider_config_service.py tests/dashboard/test_config_api.py tests/dashboard/test_config_page_frontend.py -q
python -m pytest tests/test_arteta_vision_config.py tests/test_arteta_chat_vision.py tests/dashboard/test_bot_chat.py -q
npm --prefix dashboard/web run build
```
