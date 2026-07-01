# Dashboard Vision API Key Design

## Goal

让 Dashboard 的 Config 页面可以配置独立的 `VISION_API_KEY`，并让图片识别 fallback 调用优先使用该密钥。线上 ECS 同步切换为用户指定的 vision key 和 `mimo-v2.5-pro` 模型。

## Current State

Dashboard Config 页面由后端 `ENV_WHITELIST` 自动驱动，目前已有 `IMAGE_API_KEY`、`IMAGE_API_URL`、`IMAGE_MODEL` 和 `VISION_MODEL`，但缺少 `VISION_API_KEY`。图片识别 fallback 当前使用 `IMAGE_API_URL`、`IMAGE_API_KEY` 和 `VISION_MODEL`。

## Design

1. 在 dashboard 配置白名单中加入 `VISION_API_KEY`。
2. 在 `plugins/arteta_chat.py` 中读取 `VISION_API_KEY`，图片识别 fallback 调用优先使用 `VISION_API_KEY`，未配置时回退 `IMAGE_API_KEY`。
3. 保持 `VISION_MODEL` 继续由环境配置驱动，不把模型名硬编码进代码。
4. 更新 dashboard 开发文档，说明 Config 页面包含 vision key。

## Validation

- 运行 dashboard 相关 pytest，确认新增白名单和配置更新逻辑正常。
- 运行前端 build，确认自动渲染新增配置项后构建通过。
- 在 ECS 上更新 `.env`：`VISION_API_KEY` 为用户指定 key，`VISION_MODEL=mimo-v2.5-pro`。
- 重启线上服务后，用图片识别路径实际验证 vision 调用可用。

## Safety

Dashboard 仍只返回脱敏密钥值。线上替换密钥会写入 `.env` 并影响图片识别功能，因此执行前需要用户授权；本次用户已要求继续。