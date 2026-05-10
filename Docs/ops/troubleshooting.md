# 爬坑记录汇总

本文档汇总项目开发与部署过程中遇到的所有坑、根因和解决方案，按类别组织。

---

## 1. Python 版本兼容

### 1.1 dict[str, X] 语法（需要 Python 3.9+）

- **问题**：Python 3.8 不支持 `dict[str, X]` 类型注解语法
- **报错**：`TypeError: 'type' object is not subscriptable`
- **修复**：改用 `from typing import Dict` 的 `Dict[str, X]`

### 1.2 str | None 联合类型（需要 Python 3.10+）

- **问题**：Python 3.8 不支持 `-> str | None` 语法
- **报错**：`TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`
- **修复**：改用 `-> Optional[str]`（`from typing import Optional`）
- **涉及文件**：`plugins/arteta_weekly.py` 等

### 1.3 posthog 版本冲突

- **问题**：`posthog>=4` 使用了 `dict[str, X]` 语法（需要 Python 3.9+），项目为 Python 3.8
- **修复**：降级到 `posthog<3`（锁定 `posthog==2.x`）
- **相关依赖**：ChromaDB 间接依赖 posthog

### 1.4 asyncio.TimeoutError str() 为空

- **问题**：Python 3.8 中 `asyncio.TimeoutError()` 的 `str()` 返回空字符串 `""`，导致日志只显示 `[图片识别异常：]`，无法判断具体异常类型
- **修复**：异常消息改为 `{type(e).__name__}: {e}`，优先输出异常类型名

---

## 2. ChromaDB

### 2.1 系统 sqlite3 版本过低

- **问题**：系统自带 sqlite3 3.31.1，低于 ChromaDB 要求的 3.35.0，启动时报错
- **报错**：`RuntimeError: SQLite3 version must be >= 3.35.0`
- **修复**：使用 `pysqlite3-binary` 做 monkey-patch，在 `import chromadb` 之前替换 `sys.modules["sqlite3"]`：

```python
try:
    import pysqlite3
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass
```

- **涉及文件**：`plugins/arteta_memory.py`（文件最顶部）
- **注意**：monkey-patch 代码必须在 `import chromadb` 之前执行，否则不生效

### 2.2 ChromaDB 版本兼容

- **问题**：ChromaDB 0.5.x 要求 Python 3.9+，在 Python 3.8 环境中无法安装
- **修复**：锁定 `chromadb==0.4.x`
- **pip 命令**：`pip install chromadb==0.4.24`

### 2.3 posthog 间接依赖

- **问题**：ChromaDB 0.4.x 依赖 posthog，而 `posthog>=4` 使用了 Python 3.9+ 语法
- **修复**：同时降级 posthog 到 `<3`（参见 1.3 节）

### 2.4 add_memory 时机导致 embedding 污染

- **问题**：原代码在好感度红字拼接后将消息存入 ChromaDB，`[red]【信任度上升X点】[/red]` 等标记被编码到向量中，污染语义检索
- **修复**：将 `add_memory()` 调用移到渲染标记拼接之前

---

## 3. 渲染管道

### 3.1 Python raw string tokenizer bug（Windows）

- **问题**：在 Windows 上 Python 3.12+，raw string `r"\\["` 被 tokenizer 错误解析为 2 个反斜杠（`\\`）+ `[`，而非 3 个反斜杠（`\\\`）+ `[`
- **影响**：`normalize_math_delimiters()` 中匹配 `\\[` 的正则在 Windows 上失效
- **修复**：放弃 raw string，改用 `chr(92)` 拼接：

```python
_BS = chr(92)
text = re.sub(_BS + _BS + _BS + "[" + r"([\s\S]*?)" + _BS + _BS + _BS + "]", r'$$\1$$', text)
```

- **涉及文件**：`plugins/arteta_render.py` 第 304-305 行

### 3.2 f-string 与 LaTeX 花括号冲突

- **问题**：在 f-string 中嵌入 LaTeX `\frac{dy}{dx}` 时，`{dy}` 被 Python 解释为 f-string 占位符，导致崩溃
- **报错**：`KeyError: 'dy'` / `ValueError: invalid placeholder`
- **修复**：在 f-string 中使用 `{{dy}}` 和 `{{dx}}` 转义花括号，或直接使用普通字符串（非 f-string）
- **示例**：
  ```python
  # 错误
  prompt = f"...$$\\frac{dy}{dx}$$..."
  
  # 正确（f-string 双花括号转义）
  prompt = f"...$$\\frac{{dy}}{{dx}}$$..."
  
  # 或直接使用普通字符串
  prompt = "...$$\\frac{dy}{dx}$$..."
  ```

### 3.3 Playwright quality=95 + type="png" 冲突

- **问题**：`page.screenshot(type="png", quality=95)` 中 `quality` 参数仅对 JPEG 有效，与 `type="png"` 冲突
- **报错**：`TypeError: quality is not supported for image type`
- **修复**：截图 PNG 时移除 `quality` 参数：

```python
# 错误
await page.screenshot(type="png", quality=95, full_page=True)

# 正确
await page.screenshot(type="png", full_page=True)

# 如果需要 quality 参数，使用 JPEG
await page.screenshot(type="jpeg", quality=95, full_page=True)
```

### 3.4 matplotlib RGB 色彩范围

- **问题**：matplotlib 接受 RGB 值为 0-1 浮点数，误传递 0-255 整数会导致颜色异常或报错
- **修复**：统一使用十六进制颜色字符串（如 `'#DB0007'`——阿森纳红），matplotlib 自动解析
- **涉及文件**：`plugins/arteta_render.py`、`plugins/arteta_cmath.py`、`plugins/arteta_chat.py`

### 3.5 matplotlib usetex 与中文冲突

- **问题**：`arteta_cmath.py` 全局设置 `plt.rcParams["text.usetex"] = True`，使 matplotlib 使用 LaTeX 渲染文本。但 LaTeX 的中文渲染需要 CJK 宏包，与包含中文的图表（如好感度排行柱状图）冲突
- **修复**：在绘图函数中使用 try/finally 临时禁用 usetex：

```python
def favorability_bar_chart(data, title, bar_color):
    _old_usetex = plt.rcParams.get('text.usetex', False)
    plt.rcParams['text.usetex'] = False
    try:
        return _do_bar_chart(data, title, bar_color)
    finally:
        plt.rcParams['text.usetex'] = _old_usetex
```

- **涉及文件**：`plugins/arteta_render.py` 第 203-209 行

---

## 4. 网络

### 4.1 BBC ConnectTimeout

- **问题**：服务器无法连接 `bbc.com`，`ConnectTimeout` 异常的消息为空字符串（Linux 上 `str(e)` 返回 `""`），日志无法判断失败原因
- **影响**：阿森纳周报的 BBC 新闻源始终为空
- **修复**：
  - 日志改为 `{type(e).__name__}: {e}`，至少输出异常类型
  - 新增 Guardian 新闻源作为补偿 fallback
- **当前状态**：BBC 源仍不可用，由 Guardian 和 Sky Sports 提供新闻

### 4.2 QQ CDN HTTPS 403

- **问题**：QQ 图片 CDN 的 HTTPS 端点验证严格，需要复杂的 rkey 认证，直接下载返回 HTTP 403
- **修复**：三重下载策略：
  1. httpx + HTTPS + 请求头（Referer/User-Agent）
  2. httpx + HTTP（HTTPS 降级，QQ CDN 对 HTTP 更宽松）
  3. aiohttp + HTTP（备份项目验证过的成功方案）
- **涉及文件**：`plugins/arteta_chat.py` 中的 `_download_image_bytes()` 函数

---

## 5. 容器/部署

### 5.1 Docker 文件路径隔离

- **问题**：`bot.get_image()` 返回的文件路径是 NapCat 容器内部路径（如 `/app/.config/QQ/...`），而 bot 运行在宿主机（ECS 部署）或其他容器中（Docker Compose 部署），无法直接访问
- **修复**：不依赖 `bot.get_image()` 的本地路径，改用消息段中的 `url` 字段，配合 `_download_image_bytes()` 多重策略下载
- **涉及文件**：`plugins/arteta_chat.py`

### 5.2 NapCat WebSocket 配置

- **问题**：NapCat 默认不开启 WebSocket 服务端，NoneBot 无法连接
- **修复**：编辑 `~/napcat/config/onebot11.json`，添加 WebSocket 服务端配置：

```json
{
  "ws_server": {
    "enable": true,
    "host": "127.0.0.1",
    "port": 8088
  }
}
```

- **端口**：8088，仅监听 127.0.0.1（同机部署不对外暴露）

### 5.3 Playwright Chromium 缺失

- **问题**：服务器上仅安装了 `playwright` Python 包，未安装 Chromium 浏览器，导致 HTML 截图失败
- **报错**：`playwright._impl._errors.Error: Executable doesn't exist at ...`
- **修复**：运行 `playwright install --with-deps chromium` 下载 Chromium（约 165MB）并安装系统依赖
- **系统依赖**：xvfb, libgtk-3, libnss3, libx11-xcb 等 14 个包

### 5.4 WebSocket 频繁断联

- **问题**：`asyncio.wait_for(run_tool_loop(), timeout=25)` 阻塞事件循环 25 秒，心跳包无法响应，QQ 服务器认为机器人离线
- **修复**：将 LLM 调用放入后台任务 `asyncio.create_task(delayed_response())`，主协程立即返回，不阻塞 WebSocket 心跳
- **涉及文件**：`plugins/arteta_chat.py`

---

## 6. NoneBot

### 6.1 插件加载失败

- **问题**：NoneBot 加载插件失败时仅提示插件名不显示具体原因
- **诊断方法**：检查日志中插件名附近的 ImportError/Traceback：

```bash
grep -i "error\|traceback\|import" logs/arteta_bot.log | tail -20
```

### 6.2 FinishedException 捕获顺序

- **问题**：NoneBot 的 `FinishedException` 是 `Exception` 的子类。`except Exception` 如果在 `except FinishedException` 之前，会误拦截 `FinishedException`，导致 `matcher.finish()` 无法正常终止事件处理
- **症状**：命令完成（finish）后仍然继续执行后续代码，或出现异常日志
- **修复**：`except FinishedException: raise` 必须放在 `except Exception` 之前：

```python
try:
    await cmd.finish("处理完成")
except FinishedException:
    raise      # 先捕获，放行 NoneBot 的 finish 机制
except Exception as e:
    await cmd.finish(f"出错：{e}")
```

- **涉及文件**：`plugins/arteta_chat.py`、`plugins/arteta_image.py` 等多个插件

### 6.3 后台任务异常静默吞咽

- **问题**：`asyncio.create_task(delayed_response())` 启动的后台任务如果抛出未捕获异常，事件循环默认静默吞咽，无日志、无 Traceback
- **修复**：在后台任务函数内包裹全局 `try/except`，确保所有异常路径至少打印日志并通知用户：

```python
async def delayed_response():
    try:
        answer = await asyncio.wait_for(run_tool_loop(messages), timeout=90.0)
    except asyncio.TimeoutError:
        logger.error("LLM 响应超时")
        await event.finish("处理超时，请重试")
    except Exception as e:
        logger.exception(f"后台任务异常: {e}")
        await event.finish(f"处理出错: {e}")
```

### 6.4 知识库缓存未失效

- **问题**：`save_to_knowledge_base()` 写入周报后，`arteta_knowledge.py` 的 `_file_cache` 字典未清空，LLM 聊天查询时仍返回旧缓存，看不到新写入的内容
- **修复**：写入完成后立即调用 `plugins.arteta_knowledge.clear_cache()`：

```python
from plugins.arteta_knowledge import clear_cache

save_to_knowledge_base(content)
clear_cache()  # 使缓存失效，下次查询重新读取
```

- **涉及文件**：`plugins/arteta_weekly.py`、`plugins/arteta_knowledge.py`
