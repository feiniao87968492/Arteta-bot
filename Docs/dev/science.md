# 科学问题解答与渲染管线

## 1. 背景

`/算法` 命令（兼容 `/数学`、`/物理`、`/amath`、`/代码`、`/leetcode`、`/计算`、`/战术演练` 等别名）用于解答数学、物理、算法等技术类问题。

实现于 `plugins/arteta_chat.py` 的 `handle_algo` 函数。核心挑战：LLM 返回的答案中可能包含 LaTeX 公式、代码块等复杂格式，需要在 QQ 群聊中以图片形式清晰展示。

由此衍生出两套渲染方案：基于 Playwright + KaTeX 的 HTML 渲染管线，和基于 Pillow + Pilmoji 的战术板风格图片管线。

相关文件：
- `plugins/arteta_render.py` — 渲染核心
- `plugins/arteta_cmath.py` — 旧版 LaTeX matplotlib 渲染引擎（已退役，保留供参考）
- `plugins/arteta_chat.py` — `/算法` 命令入口，调用渲染管线
- `templates/arteta_render.html` — HTML 渲染用的 Jinja2 模板

---

## 2. Agent 科学工具路由

Agent 模式下的科学工具由 `plugins/arteta_agent/planner.py` 做前置路由。这里分成两层：

1. **高置信强制调用**：只有明确出现算法、代码、物理、数学题意图，或高置信数学符号时，才直接强制调用 `solve_algorithm_problem` / `solve_code_question` / `solve_science_question` / `solve_math_question`，并把工具调用写入 trace。
2. **本轮 schema 隐藏**：如果当前消息没有技术题上下文，planner 会把上述科学工具从本轮 LLM 可见工具 schema 中排除，避免模型把普通聊天误调成解题工具。

比分式短语需要特别注意：`1-0`、`2:1`、`3比0` 这类文本在没有“求解、计算、题目、证明、方程”等技术上下文时，按普通聊天或足球比分处理，不应触发 `solve_math_question`。如果用户明确说“计算 1-0 等于多少”或“这道题 1-0 怎么算”，才允许进入数学工具。

相关回归：

```bash
python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_does_not_expose_math_tool_for_scoreline_chat -q
python tools/verify_features.py --suite agent_loop --case does_not_expose_math_tool_for_scoreline_chat
```
### 2.1 信息工具路由：LLM 自主选择

`web_search`、`web_fetch`、`verify_recent_claim`、`query_group_memory`、`get_recent_group_context` 这类信息工具不再由 planner 通过关键词强制调用。planner 只负责把工具 schema 暴露给 LLM，并通过 `execute_tool_call()` 执行权限、超时和 trace 记录。

原因：`今天/昨天/最近/比分/预测` 这类词既可能表示公网实时事实，也可能表示“你昨天说过什么”的群内记忆。服务端 marker 无法可靠区分，强制调用 web verifier 会让“塔子你还记得你昨天预测的这场比赛的比分吗”绕过记忆工具，甚至在 verifier 没查到来源时阻断正常聊天。

Agent prompt 中的约束是：回忆类表达（“还记得/昨天你说过/刚才/之前/预测过/你当时”）优先选择 `query_group_memory` 或 `get_recent_group_context`；明确要求公网核验、最新新闻、官宣来源或实时动态时，再选择 web 工具。web 工具无可靠结果时，LLM 仍必须继续回到原问题作答，不能把 verifier 的失败文本当最终回复。

相关回归：

```bash
python -m pytest tests/test_arteta_agent_registry.py::test_agent_loop_lets_llm_choose_memory_for_yesterday_prediction_score -q
python tools/verify_features.py --suite agent_loop --case lets_llm_choose_memory_for_yesterday_prediction_score
python tools/verify_features.py --suite agent_loop --case continues_after_unavailable_web_verification
```
---

## Appendix: Optional GrokSearch Backend

`plugins/arteta_agent/tools/web_access.py` can use GrokSearch as the first backend for `web_search`, `web_fetch`, and `verify_recent_claim`. It also registers a standalone `grok_search` tool for Grok-only searches.

For X/Twitter original posts, `fetch_x_post` can optionally use a separate authenticated browser bridge before public fallback paths. This is the recommended way to read posts that require login.

Important: the upstream GrokSearch project is a FastMCP stdio server. `ARTETA_GROKSEARCH_API_URL` must point at an HTTP bridge/gateway that exposes its MCP tools as HTTP endpoints for the bot process. The bot does not run the Python 3.10+ MCP server in-process.

Configuration:

```env
ARTETA_GROKSEARCH_API_URL=https://your-groksearch-service
ARTETA_GROKSEARCH_API_KEY=...
ARTETA_GROKSEARCH_MODEL=
ARTETA_GROKSEARCH_TIMEOUT=80
ARTETA_WEB_SEARCH_GROK_TIMEOUT=10
ARTETA_X_FETCH_API_URL=http://127.0.0.1:8801
ARTETA_X_FETCH_API_KEY=shared-secret
```

Bridge startup example:

```bash
# Python 3.10+ environment
pip install "git+https://github.com/GuDaStudio/GrokSearch@grok-with-tavily" fastapi uvicorn

export GUDA_API_KEY=...
export ARTETA_GROKSEARCH_BRIDGE_KEY=shared-secret
python -m uvicorn tools.groksearch_http_bridge:app --host 127.0.0.1 --port 8799
```

Then configure the bot:

```env
ARTETA_GROKSEARCH_API_URL=http://127.0.0.1:8799
ARTETA_GROKSEARCH_API_KEY=shared-secret
```

Authenticated X bridge startup example:

```bash
# One-time browser profile setup on the server. Use a dedicated X account, not a personal main account.
export ARTETA_ENV_FILE=/opt/arteta_bot/.env.prod
export ARTETA_X_FETCH_PROFILE_DIR=/opt/arteta_bot/data/x_browser_profile
python -m tools.x_fetch_bridge --login

# Service process, bound to localhost only.
python -m uvicorn tools.x_fetch_bridge:app --host 127.0.0.1 --port 8801
```

Security notes for the X bridge:

- Use a dedicated X account with the minimum needed access.
- Keep `ARTETA_X_FETCH_PROFILE_DIR` readable only by the bot service user.
- Do not expose the bridge to the public internet; bind to `127.0.0.1`.
- The bridge only accepts `x.com` / `twitter.com` status URLs and returns extracted text, not raw cookies or page HTML.

When `ARTETA_GROKSEARCH_API_URL` and `ARTETA_GROKSEARCH_API_KEY` are both set, the Agent web tools try GrokSearch first:

- `grok_search` posts to `<ARTETA_GROKSEARCH_API_URL>/web_search` only; it does not fall back to Bing/DuckDuckGo/Jina, so the model can explicitly choose a Grok-backed path for X/Twitter and high-freshness news checks
- `web_search` posts to `<ARTETA_GROKSEARCH_API_URL>/web_search`; if the response only contains `session_id`, the bot follows with `<ARTETA_GROKSEARCH_API_URL>/get_sources`
- `fetch_x_post` extracts the tweet/status id from `x.com` or `twitter.com`, tries the authenticated X bridge when configured, then the public syndication payload, then public X mirrors with author validation, then falls back to GrokSearch fetch, and returns a clear `[x-post-unavailable]` message when the original post text cannot be read
- `web_fetch` posts to `<ARTETA_GROKSEARCH_API_URL>/web_fetch`
- `verify_recent_claim` reuses the same search chain, so it also benefits from GrokSearch

Security: `web_fetch`, `analyze_links`, Grok-backed source screenshots, and `read_document` reject loopback/private/link-local/internal hosts before fetching and re-check the final URL after redirects. Plain web/document fetches stream response bodies and stop buffering at their byte limits instead of downloading the full response first.

If GrokSearch returns no usable result, times out, or raises an error, the existing Bing/DuckDuckGo/Jina fallback chain still runs. This keeps the bot usable when the optional backend is down.

GrokSearch itself is a separate Python 3.10+ FastMCP service. The bot runtime remains Python 3.8 compatible and does not import GrokSearch as a library.

Deployment fallback:

`tools/groksearch_http_bridge.py` first tries to call the upstream `grok_search` FastMCP tools. If that package is not importable on the server, the HTTP bridge remains usable by falling back to the project's built-in Bing/DuckDuckGo/Jina search and page fetch helpers. When `GROK_API_URL`, `GROK_API_KEY`, and `GROK_MODEL` are configured, the fallback path also asks the Grok-compatible model for a short research summary, while still returning normal `results` / `content` fields for the bot.

The bridge can load `/opt/arteta_bot/.env.prod` directly through `ARTETA_ENV_FILE`, so supervisor should not shell-source `.env.prod`; that file may contain values that are valid for NoneBot dotenv parsing but invalid shell syntax.

Bot-side observability: when `grok_search`, `web_search`, `web_fetch`, or `verify_recent_claim` returns data through the GrokSearch bridge, the tool observation starts with `[grok]`. Agent Trace also records this as `markers:[grok]`, without storing raw search results or secrets. If the final answer was produced after a `[grok]` observation, the planner prefixes the user-facing answer with `[grok]` as well, so rendered replies show the source path at the top instead of only inside trace details.

Grok source screenshots: `grok_search`, Grok-backed `web_search`, and Grok-backed `verify_recent_claim` append a `[LinkSnapshotImage: ...]` artifact for the first safe, screenshotable source URL returned by GrokSearch. The screenshot is captured through the existing Playwright link snapshot path and is sent by `arteta_chat.py` after the main rendered reply. If the first source cannot be screenshotted, the tool tries the next source; if all screenshots fail, the Grok text result is still returned without blocking the reply.

Prompt priority and routing: the Agent tool principles explicitly tell the model to prefer `grok_search` or `verify_recent_claim` for latest news, transfers, injuries, official announcements, X/Twitter/social posts, and recent circulating claims. In addition, `planner.detect_forced_web_verification_args()` identifies public current-fact football questions such as recent Arsenal transfer status, then chooses the first-hop tool from Behavior Policy key `route.public_current_fact.preferred_tool`. The default preferred tool is now `web_search`, which gives GrokSearch a bounded first hop and then falls back to Bing/DuckDuckGo/Jina. Supported preferred tools are `web_search`, `verify_recent_claim`, and `grok_search`; if the configured tool is unavailable or disabled, planner falls back through `web_search` / `verify_recent_claim` / `grok_search`. Natural-language instructions like "以后类似这种实事性的问题统一走grok-research" are parsed into this route policy. Local memory questions such as "what did you say earlier" remain routed through memory/recent-context tools. If a concrete X/Twitter status URL is known, the model should call `fetch_x_post` instead of generic `web_fetch`. `[x-post-unavailable]` is treated as unavailable evidence in trace and follow-up answer handling, not as a successful original-post read.

Compatibility notes: the HTTP bridge filters request fields against the installed upstream GrokSearch tool signature before invocation, because some GrokSearch versions accept `query/platform/model/extra_sources` but not the bot-side `max_results/freshness` fields. Bot-side parsing also accepts GrokSearch responses that return Markdown links in `content` with a `session_id` but no structured `sources` list, so X/Twitter citations such as `https://x.com/.../status/...` can still surface as `[grok]` search results.

Timeout: `ARTETA_GROKSEARCH_TIMEOUT` defaults to 80 seconds and is read lazily by the standalone Grok-backed tools. `ARTETA_WEB_SEARCH_GROK_TIMEOUT` defaults to 10 seconds and only controls the GrokSearch first hop inside generic `web_search`; when that short budget is exceeded, `web_search` falls back to the regular Bing/DuckDuckGo/Jina chain instead of waiting for the full GrokSearch timeout.

Fallback search quality: the bridge expands Chinese match queries such as `阿根廷和佛得角的比赛情况` into English football score/result variants and ranks sports result pages, score pages, and Chinese sports match pages above encyclopedic team/country pages. This keeps match-result questions from being dominated by generic country profiles.
For Argentina/Cape Verde style match queries, the bridge also appends Chinese score-oriented variants such as `阿根廷 佛得角 世界杯 比分 3-2`, because the current search backend returns the CCTV match page reliably for those Chinese terms while English-only queries may degrade into generic team/country pages.

Verification ranking: `verify_recent_claim` also scores match-result evidence before source-level sorting. For match/score claims, a page containing both teams and an explicit score can beat a generic official team profile, so a FIFA squad page will not override a CCTV/ESPN/score-page result for the actual match.



---

## 3. 双渲染架构

渲染管线的决策点在 `handle_algo` 和 `delayed_response`（聊天回复）中：

```
if needs_html_render(answer):
    html_answer = answer 替换颜色标签为 HTML 标签
    try:
        img_bytes = await html_to_image(html_answer)
    except Exception:
        img_bytes = text_to_tactical_board(answer)
else:
    img_bytes = text_to_tactical_board(answer)
```

### 3.1 needs_html_render() — 检测是否需要 HTML 渲染

定义于 `arteta_render.py`，核心逻辑：

```python
def needs_html_render(text: str) -> bool:
    text = normalize_math_delimiters(text)
    if '```' in text:        # 代码块
        return True
    if re.search(r'\$[^$]+\$', text):  # 行内/行间公式
        return True
    if re.search(r'(?m)^    ', text):   # 缩进代码
        return True
    return False
```

先调用 `normalize_math_delimiters` 将 `\(...\)` / `\[...\]` 转为 `$...$` / `$$...$$`，再统一检测。

### 3.2 HTML 渲染路径 — html_to_image()

整个渲染流程：

1. **输入**: LLM 返回的纯文本（含颜色标签）
2. **颜色标签替换**: 通过 `style_tags_to_html()` 统一处理 `[red]`、`[blue]`、`[color=green]`、`[color=#16a34a]`、`[bold]`、`[large]`、`[scale=...]`
3. **数学定界符归一化**: `normalize_math_delimiters()`
4. **Jinja2 模板渲染**: 将文本注入 `templates/arteta_render.html`
5. **Playwright Chromium 打开页面**: `page.set_content(html_content, wait_until="networkidle")`
6. **等待 KaTeX + marked.js 渲染完成**: 轮询 `window.__RENDERED__ === true`
7. **计算内容高度**: `document.body.scrollHeight`
8. **全页截图**: `page.screenshot(type="png", full_page=True)`
9. **返回 bytes** → 通过 `MessageSegment.image()` 发送到 QQ

模板依赖的外部 CDN 资源：
- **KaTeX** (v0.16.10): LaTeX 公式渲染
- **marked.js** (latest): Markdown → HTML 转换
- **highlight.js** (v11.9.0): 代码语法高亮

模板渲染过程的关键细节：marked.js 解析 Markdown 时，`$...$` 会被误认为普通文本。解决办法是先通过正则把 `$$...$$` 和 `$...$` 替换为占位符 `MATHBLOCK{n}END`，marked 解析完 HTML 后再把占位符替换回原始公式字符串，最后交给 KaTeX 的 `renderMathInElement` 渲染。

### 3.3 PIL 回退路径 — text_to_tactical_board()

当 HTML 渲染失败或检测到无需 HTML 渲染时，使用 Pillow + Pilmoji 生成图片。

图片规格：
- 画布宽度: 1500px
- 内边距: 80px
- 页头高度: 120px
- 行间距: 30px
- 字体: `msyh.ttc`（微软雅黑），若缺失则回退 PIL 默认字体（质量严重下降）
- 背景色: `#F8FAFC`
- 顶部红色装饰条: 15px 高，`#DB0007`（阿森纳红）
- 页头标题: "PREMIER LEAGUE | SITUATION ROOM"，红色

支持 `[red]...[/red]`、`[blue]...[/blue]`、`[color=...]...[/color]` 颜色标签解析（通过正则按 chunk 拆分后逐 chunk 设置颜色）。

支持 `---` 分隔线渲染（灰色水平线）。

预处理器会去除 Markdown 的 `*`、`#`、列表符号 `-+`、`数字.` 等。

---

## 4. 关键函数详解

### 4.1 html_to_image(html_text) -> bytes

```python
async def html_to_image(markdown_text: str) -> bytes:
```

职责：将 Markdown 文本渲染为 PNG 图片。

流程：
1. 调用 `normalize_math_delimiters(markdown_text)` 统一公式定界符
2. 通过 Jinja2 模板引擎渲染 HTML
3. 从全局 Playwright 浏览器实例新建页面
4. 设置 viewport 1500x800, device_scale_factor=2（2x 清晰度）
5. 注入 HTML 内容，等待 `networkidle`
6. 等待 `window.__RENDERED__ === true`（超时 15s）
7. 额外 sleep 0.5s 确保渲染完成
8. 获取实际内容高度，调整 viewport
9. 全页截图，返回 PNG bytes
10. 最终关闭页面

### 4.2 needs_html_render(text) -> bool

见 2.1 节。关键点：必须先归一化定界符再检测，否则 `\(...\)` 格式不会被检测到。

### 4.3 normalize_math_delimiters(text) -> str

```python
def normalize_math_delimiters(text: str) -> str:
```

将 LaTeX 风格的 `\(...\)` 和 `\[...\]` 转换为 KaTeX 兼容的 `$...$` 和 `$$...$$`。

实现细节（重要爬坑）：
- 因为 Python 3.12+ Windows 上的 tokenizer bug（`r"\\["` 被错误解析为两个反斜杠而非三个），无法使用传统的 raw string 正则
- 改用 `chr(92)` 拼接方式：`_BS = chr(92)`，然后 `re.sub(_BS + _BS + _BS + "[" ...)` 等效于查找 `\\\[` 模式

转换逻辑：
- `\\[` + 任意字符（含换行）+ `\\]` → `$$...$$`（行间公式）
- `\\(` + 任意字符（含换行）+ `\\)` → `$...$`（行内公式）

### 4.4 text_to_tactical_board(text) -> bytes

见 2.3 节。使用 Pillow 的 ImageDraw 和 Pilmoji（支持 emoji 渲染的 PIL 扩展）。

关键实现细节：
- 文本换行：逐字符测量宽度，超出 `CANVAS_WIDTH - 2*PADDING` 时换行
- 颜色标签处理：通过 `parse_inline_style_chunks()` 解析 `[red]`、`[blue]`、`[color=...]`、`[bold]`、`[large]`、`[scale=...]`
- 每个 chunk 携带颜色信息，逐 chunk 渲染
- 支持 emoji（通过 Pilmoji）
- 分隔线 `---` 渲染为灰色横线

### 4.5 close_browser()

```python
async def close_browser():
```

关闭全局 Playwright 浏览器实例和 Playwright 进程。在插件卸载或 bot 关闭时调用，避免资源泄漏。

---

## 5. 模板

模板文件: `templates/arteta_render.html`

技术栈：
- **KaTeX** v0.16.10 — LaTeX 公式渲染，从 CDN 加载核心库和 auto-render 扩展
- **marked.js** — Markdown → HTML 转换
- **highlight.js** v11.9.0 — 代码块语法高亮（github-dark 主题）

页面结构：
- 顶部红色横条（`.topbar`，15px, #DB0007）
- 标题 "ARSENAL | TACTICAL BOARD"（38px, 红色）
- 灰色分隔线（`.separator`）
- 内容区 `<div id="content">` — 由 JavaScript 填充

CSS 要点：
- 背景色 `#f8fafc`，字体 `Segoe UI`, `PingFang SC`, `Microsoft YaHei`
- `strong` 标签渲染为阿森纳红色
- KaTeX 公式字号 1.1em
- 代码块深色背景 `#0d1117`，圆角 8px，使用等宽字体
- 引用块左侧红色竖条
- 表格红色表头
- 预定义颜色类：`.arsenal-red` (#DB0007) 和 `.arsenal-blue` (#0284C7)；其它受控颜色通过 `[color=...]` 转为 inline `style="color: ..."`

JavaScript 渲染流程：
1. 通过 Jinja2 的 `tojson` 过滤器注入原始文本
2. 检测是否含有 `$` 符号
3. 若有公式：先用正则提取 `$$...$$` 和 `$...$` 替换为占位符，再调用 `marked.parse()`，最后还原占位符
4. 若无公式：直接 `marked.parse(raw)`
5. 调用 `renderMathInElement()` 渲染 LaTeX（`throwOnError: false`）
6. 调用 `hljs.highlightAll()` 高亮代码块
7. 设置 `window.__RENDERED__ = true` 通知 Python 端

---

## 6. 标题效果：颜色标签系统

支持受控颜色标签，在纯文本和 HTML 渲染中均可使用：

| 标签 | HTML 替换 | 颜色 | RGB |
|------|-----------|------|-----|
| `[red]...[/red]` | `<span class="arsenal-red">` | 阿森纳红 | `#DB0007` |
| `[blue]...[/blue]` | `<span class="arsenal-blue">` | 阿森纳蓝 | `#0284C7` |
| `[color=green]...[/color]` | `<span style="color: green">` | 绿色 | `green` / `#16a34a` |
| `[color=#RRGGBB]...[/color]` | `<span style="color: #RRGGBB">` | 自定义安全十六进制色 | `#RGB` / `#RRGGBB` |

HTML 渲染路径中，Python 端在传入 `html_to_image()` 之前将样式标签替换为对应的 `<span>` 标签。普通聊天和 agent 自主 `render_markdown_to_image` 工具都走同一套 `style_tags_to_html()` 转换，避免 `[color=green]` 等标记被当作普通 Markdown 文本。

Agent 长期偏好写入会把“深绿”解析为 `#006400`，“浅绿”解析为 `#86efac`，“亮绿”解析为 `#22c55e`；用户也可以直接说 `#006400` 或 `006400`。

Behavior Policy 中的 `render.reply_body.name_highlight` 会作为名字高亮颜色读取，`render.reply_body.target_names` 可用 `、`、`,`、`;` 或换行分隔多个目标名；裸色值如 `006400` 会规范为 `#006400` 后再应用。

PIL 回退路径中，`text_to_tactical_board()` 内部通过正则解析颜色标签，逐 chunk 设置不同的 PIL 颜色值：
- red: `(220, 38, 38)`
- blue: `(2, 132, 199)`
- green: `(22, 163, 74)`
- 默认文本: `(30, 41, 59)`

其它受控命名色或 `#RGB/#RRGGBB` 颜色会转为对应 RGB 值。

---

## 7. 爬坑汇总

### 7.1 Python raw string tokenizer bug on Windows

在 Windows 上 Python 3.12+，raw string `r"\\["` 会被 tokenizer 错误解析为两个反斜杠（`\\`）加 `[`，而非三个反斜杠（`\\\`）加 `[`。

影响：`normalize_math_delimiters()` 中本应匹配 `\\[`（literal backslash + backslash + bracket）的正则表达式在 Windows 上失效。

解决方案：放弃 raw string，改用 `chr(92)` 拼接：

```python
_BS = chr(92)
text = re.sub(_BS + _BS + _BS + "[" + r"([\s\S]*?)" + _BS + _BS + _BS + "]", r'$$\1$$', text)
```

### 7.2 f-string 与 LaTeX 花括号冲突

在 `/算法` 的 system prompt 中，需要给 LLM 举例 LaTeX 分式 `\frac{dy}{dx}`。但如果使用 f-string 构造 prompt，`{}` 会被解释为 f-string 的占位符。

解决方案：在 prompt 中使用 `{{` 和 `}}` 转义花括号：

```python
algo_prompt = (
    "...长公式/独立公式用双 $$ 包裹（如 $$\\int_a^b f(x)dx$$、$$\\frac{{dy}}{{dx}}$$）。..."
)
```

### 7.3 Playwright quality=95 + type="png" 冲突

`screenshot(type="png")` 不接受 `quality` 参数。quality 参数仅对 `type="jpeg"` 有效。

错误的代码：
```python
await page.screenshot(type="png", quality=95, full_page=True)
# 会抛出异常
```

正确的代码：
```python
await page.screenshot(type="png", full_page=True)
```

### 7.4 matplotlib usetex 与中文冲突

`arteta_cmath.py` 全局设置了 `plt.rcParams["text.usetex"] = True`，这使得 matplotlib 使用 LaTeX 渲染所有文本。但 LaTeX 的中文支持需要 CJK 宏包，且与某些 matplotlib 操作冲突。

影响：`favorability_bar_chart()` 绘制的柱状图包含中文标签，在 `usetex=True` 下会渲染失败。

解决方案：在绘图函数中使用 try/finally 临时禁用 usetex：

```python
def favorability_bar_chart(data, title, bar_color):
    _old_usetex = plt.rcParams.get('text.usetex', False)
    plt.rcParams['text.usetex'] = False
    try:
        return _do_bar_chart(data, title, bar_color)
    finally:
        plt.rcParams['text.usetex'] = _old_usetex
```

### 7.5 缺失 Chromium（服务器环境）

Playwright 需要 Chromium 浏览器二进制文件。默认 `pip install playwright` 不会下载浏览器。

需要在部署时运行：
```bash
playwright install --with-deps chromium
```

`--with-deps` 还会自动安装操作系统级别的依赖（详见第 7 节）。

未安装时的报错：
```
playwright._impl._errors.Error: Executable doesn't exist at ...
```

---

## 8. 服务器环境依赖

Linux 服务器上运行 Playwright Chromium 需要以下系统依赖：

### 核心依赖
- `xvfb` — 虚拟 X 服务器（无头显示），用于在无显示器环境中运行浏览器

### GTK/GDK 库
- `libgtk-3-0` 或 `libgtk-3-dev`
- `libgdk-pixbuf2.0-0`

### NSS（网络安全服务）
- `libnss3`

### 其他常用依赖
- `libxcb-xfixes0`
- `libxkbcommon0`
- `libatk-bridge2.0-0`
- `libdrm2`
- `libxshmfence1`
- `libasound2`（音频，可选）

Debian/Ubuntu 一键安装：
```bash
apt-get install -y xvfb libgtk-3-0 libnss3 libxcb-xfixes0 libxkbcommon0 \
    libatk-bridge2.0-0 libdrm2 libxshmfence1
```

或直接使用 Playwright 的自动依赖安装：
```bash
playwright install-deps chromium
```

---

## 附录：渲染管线架构图（伪代码）

```
用户输入 "/算法 求导公式"
    │
    ▼
handle_algo() in arteta_chat.py
    │
    ├─ call_algo_llm() → LLM 返回含 LaTeX 公式的文本
    │
    ▼
needs_html_render(answer) ?
    │
    ├─ True ──────────────────────────────────────
    │   │  替换 [red]/[blue] 为 HTML 标签
    │   │  normalize_math_delimiters()
    │   │  Jinja2 + template → HTML
    │   │  Playwright Chromium 打开 HTML
    │   │  marked.js → KaTeX → highlight.js
    │   │  screenshot → PNG bytes
    │   │
    │   └─ 失败 → text_to_tactical_board(answer)
    │
    └─ False ─────────────────────────────────────
        │  text_to_tactical_board(answer)
        │  → Pillow + Pilmoji 直接渲染为战术板图片
        │
        ▼
    MessageSegment.image(img_bytes) → QQ 群
```
