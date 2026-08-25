# AI 图片生成 — 开发文档

## 背景

机器人提供两条 AI 画图命令：

- **画图** — 基础图片生成，使用 gpt-image-2 模型
- **画图-pro**（别名 `画图pro`、`画图2`）— 高级图片生成，使用独立 API endpoint
- **图生图** — 基于参考图片的二次生成

实现文件：`plugins/arteta_image.py`

---

## 画图（基础版）

### 指令

```
画图 <画面描述>
```

### 配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `IMAGE_API_KEY` | （必填） | gpt-image-2 API 密钥 |
| `IMAGE_API_URL` | `https://www.boxying.com` | API 端点地址 |
| `IMAGE_MODEL` | `gpt-image-2` | 模型名称 |

### 调用流程

1. 从消息中提取纯文本作为 prompt
2. 向 `{IMAGE_API_URL}/v1/images/generations` 发起 POST 请求
3. 请求体：`{ "model": IMAGE_MODEL, "prompt": prompt, "n": 1, "size": "1024x1024" }`
4. 请求头：`Authorization: Bearer {IMAGE_API_KEY}`
5. 超时时间：180 秒
6. 响应处理：
   - 优先读取 `data[0].url`，下载图片二进制后以 `MessageSegment.image` 发送
   - 回退读取 `data[0].b64_json`，base64 解码后发送
   - 两者均缺失则报错

### 错误处理

- **503 + "No available channel"** — 提示词可能触发安全过滤，提示用户换一种描述
- **401** — 认证失败，提示联系管理员检查配置
- **超时（ReadTimeout / timeout / timed out）** — 队列长或提示词复杂，提示稍后重试
- 其他异常 — 输出错误信息并写入 `/tmp/imgerr.log`

---

## 画图-pro / 画图pro / 画图2

### 指令

```
画图-pro <画面描述>
画图pro <画面描述>
画图2 <画面描述>
```

### 配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `IMAGE2_API_KEY` | （必填） | 高级画图 API 密钥 |
| `IMAGE2_API_URL` | `https://www.boxying.com` | 高级画图 API 端点地址 |
| `IMAGE2_MODEL` | （按实际情况配置） | 高级画图模型名称 |

### 调用流程

与基础版类似，但请求发送至 `{IMAGE2_API_URL}/v1/images/generations`，使用 `IMAGE2_API_KEY` 鉴权。其余参数结构（model、prompt、n、size）与基础版一致。响应格式与图片发送逻辑完全相同。

---

## 图生图（Image-to-Image）

### 指令

```
图生图 <修改要求>
```

必须**回复一条包含图片的消息**，或在同一条消息中**附带图片**。

### 调用流程

1. 从消息中提取 prompt（去掉前缀 `图生图`）
2. 查找参考图片 URL：
   - 优先从回复消息（`reply` 类型）中提取图片
   - 其次从当前消息中提取图片
3. 下载参考图片
4. 图片预处理：
   - 转换为 RGB 模式
   - 扩展为正方形（白色背景填充）
   - 缩放到 1024x1024（`Image.LANCZOS`）
   - 保存为 PNG 格式
5. 调用 `{IMAGE_API_URL}/v1/images/edits`：
   - 请求头：`Authorization: Bearer {IMAGE_API_KEY}`
   - 表单数据：`model`、`prompt`、`n`、`size`
   - 文件：`image`（PNG 二进制）
6. 响应处理：与画图命令相同（优先 url，回退 b64_json）
7. 超时时间：180 秒

### 错误处理

- 未找到参考图片 — 提示用户回复或附带图片
- 图片下载失败（非 200）— 提示下载失败
- 与画图命令相同的错误码处理（503 安全过滤、401 认证失败等）

---

## 补充说明

- 两个命令共享相同的超时设置（180 秒），适合复杂或队列较长的生成请求
- 图片生成使用固定尺寸 **1024x1024**，图生图命令内部会将任意尺寸的输入图片预处理为正方形后再调用 API
- 所有 API 密钥和端点均通过 NoneBot2 的 `.env` / `.env.*` 配置文件注入，在插件启动时通过 `driver.config` 读取
- 错误日志（基础画图命令的异常）会追加写入 `/tmp/imgerr.log`，便于排查服务端问题
- 由于使用了 `FinishedException` 捕获与重抛，`draw_cmd.finish()` 和 `img2img_cmd.finish()` 能正常终止事件处理，不会触发外层异常捕获造成误报
