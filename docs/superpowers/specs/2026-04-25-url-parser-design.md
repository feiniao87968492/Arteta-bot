# URL 自动解析与评价功能设计

## 概述
在群聊中检测到 URL 链接时，自动抓取网页内容并提取摘要，以阿尔特塔口吻进行评价后以图片形式回复。

## 触发方式
- **自动触发**：群内任何包含 `https?://` 链接的消息
- **跳过规则**：机器人自身消息、私聊消息
- **优先级**：`priority=12, block=False`，不拦截其他指令处理

## 架构

### 新文件
- `plugins/arteta_url.py` — URL 检测、抓取、提取、评价完整链路

### 流程
```
群消息含 URL → 正则匹配 → httpx 抓取网页 → BeautifulSoup 提取标题/描述/摘要
    → DeepSeek API 评价（阿尔特塔口吻）→ 图片渲染 → 群回复
```

### URL 检测
- 正则：`https?://[^\s]+`
- 仅匹配 `GroupMessageEvent`
- `block=False` 允许消息继续传递给其他处理器

### 网页抓取
- 使用 `httpx.AsyncClient`，超时 15 秒，跟踪重定向
- User-Agent 模拟浏览器
- 仅抓取文本内容，不下载资源文件

### 内容提取
- 使用 `BeautifulSoup + lxml` 解析 HTML
- 提取项：`<title>` + `<meta name="description">` + 正文前 2000 字
- 清理多余空白和换行

### 评价生成
- 调用 DeepSeek API（复用 `arteta_chat.py` 的 API Key）
- 提示：以阿尔特塔口吻点评链接内容，要求简短有力（100-200 字）
- 称呼分享者为「小伙子」
- 保持教练的压迫感和人格魅力

### 回复格式
- 复用 `text_to_tactical_board()` 渲染为图片
- 图片中包含：链接摘要 + 阿尔特塔点评

### 错误处理
- 抓取失败/超时：静默忽略，不发送消息
- 内容为空：仅评论链接标题或 URL
- API 调用失败：静默忽略

## 依赖变更
- `pyproject.toml` 新增：`beautifulsoup4`, `lxml`
