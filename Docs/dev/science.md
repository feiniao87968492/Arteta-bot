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

## 2. 双渲染架构

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

### 2.1 needs_html_render() — 检测是否需要 HTML 渲染

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

### 2.2 HTML 渲染路径 — html_to_image()

整个渲染流程：

1. **输入**: LLM 返回的纯文本（含颜色标签）
2. **颜色标签替换**: `[red]` → `<span class="arsenal-red">`，`[blue]` → `<span class="arsenal-blue">`
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

### 2.3 PIL 回退路径 — text_to_tactical_board()

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

支持 `[red]...[/red]` / `[blue]...[/blue]` 颜色标签解析（通过正则按 chunk 拆分后逐 chunk 设置颜色）。

支持 `---` 分隔线渲染（灰色水平线）。

预处理器会去除 Markdown 的 `*`、`#`、列表符号 `-+`、`数字.` 等。

---

## 3. 关键函数详解

### 3.1 html_to_image(html_text) -> bytes

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

### 3.2 needs_html_render(text) -> bool

见 2.1 节。关键点：必须先归一化定界符再检测，否则 `\(...\)` 格式不会被检测到。

### 3.3 normalize_math_delimiters(text) -> str

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

### 3.4 text_to_tactical_board(text) -> bytes

见 2.3 节。使用 Pillow 的 ImageDraw 和 Pilmoji（支持 emoji 渲染的 PIL 扩展）。

关键实现细节：
- 文本换行：逐字符测量宽度，超出 `CANVAS_WIDTH - 2*PADDING` 时换行
- 颜色标签处理：对每段文本，用 `re.split(r'(\[blue\].*?\[/blue\]|\[red\].*?\[/red\])', ...)` 拆分为 chunk
- 每个 chunk 携带颜色信息，逐 chunk 渲染
- 支持 emoji（通过 Pilmoji）
- 分隔线 `---` 渲染为灰色横线

### 3.5 close_browser()

```python
async def close_browser():
```

关闭全局 Playwright 浏览器实例和 Playwright 进程。在插件卸载或 bot 关闭时调用，避免资源泄漏。

---

## 4. 模板

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
- 预定义颜色类：`.arsenal-red` (#DB0007) 和 `.arsenal-blue` (#0284C7)

JavaScript 渲染流程：
1. 通过 Jinja2 的 `tojson` 过滤器注入原始文本
2. 检测是否含有 `$` 符号
3. 若有公式：先用正则提取 `$$...$$` 和 `$...$` 替换为占位符，再调用 `marked.parse()`，最后还原占位符
4. 若无公式：直接 `marked.parse(raw)`
5. 调用 `renderMathInElement()` 渲染 LaTeX（`throwOnError: false`）
6. 调用 `hljs.highlightAll()` 高亮代码块
7. 设置 `window.__RENDERED__ = true` 通知 Python 端

---

## 5. 标题效果：颜色标签系统

支持三种颜色标签，在纯文本和 HTML 渲染中均可使用：

| 标签 | HTML 替换 | 颜色 | RGB |
|------|-----------|------|-----|
| `[red]...[/red]` | `<span class="arsenal-red">` | 阿森纳红 | `#DB0007` |
| `[blue]...[/blue]` | `<span class="arsenal-blue">` | 阿森纳蓝 | `#0284C7` |
| `[green]...[/green]` | — | — | — |

HTML 渲染路径中，Python 端在传入 `html_to_image()` 之前将颜色标签替换为对应的 `<span>` 标签，CSS 中定义了 `.arsenal-red` 和 `.arsenal-blue` 类。

PIL 回退路径中，`text_to_tactical_board()` 内部通过正则解析颜色标签，逐 chunk 设置不同的 PIL 颜色值：
- red: `(220, 38, 38)`
- blue: `(2, 132, 199)`
- 默认文本: `(30, 41, 59)`

注意：`[green]` 标签虽然在 prompt 中有提及，但在 `text_to_tactical_board` 中尚未实现。

---

## 6. 爬坑汇总

### 6.1 Python raw string tokenizer bug on Windows

在 Windows 上 Python 3.12+，raw string `r"\\["` 会被 tokenizer 错误解析为两个反斜杠（`\\`）加 `[`，而非三个反斜杠（`\\\`）加 `[`。

影响：`normalize_math_delimiters()` 中本应匹配 `\\[`（literal backslash + backslash + bracket）的正则表达式在 Windows 上失效。

解决方案：放弃 raw string，改用 `chr(92)` 拼接：

```python
_BS = chr(92)
text = re.sub(_BS + _BS + _BS + "[" + r"([\s\S]*?)" + _BS + _BS + _BS + "]", r'$$\1$$', text)
```

### 6.2 f-string 与 LaTeX 花括号冲突

在 `/算法` 的 system prompt 中，需要给 LLM 举例 LaTeX 分式 `\frac{dy}{dx}`。但如果使用 f-string 构造 prompt，`{}` 会被解释为 f-string 的占位符。

解决方案：在 prompt 中使用 `{{` 和 `}}` 转义花括号：

```python
algo_prompt = (
    "...长公式/独立公式用双 $$ 包裹（如 $$\\int_a^b f(x)dx$$、$$\\frac{{dy}}{{dx}}$$）。..."
)
```

### 6.3 Playwright quality=95 + type="png" 冲突

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

### 6.4 matplotlib usetex 与中文冲突

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

### 6.5 缺失 Chromium（服务器环境）

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

## 7. 服务器环境依赖

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
