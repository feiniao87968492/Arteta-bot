# HTML + KaTeX + Playwright 渲染管道实现方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) for syntax tracking.

**Goal:** 为 arteta bot 添加 HTML → KaTeX(公式) + highlight.js(代码) → Playwright 截图渲染管道，解决 `算法` 指令中公式和代码无法正确显示的问题。

**Architecture:** 新建共享渲染模块 `arteta_render.py`，提取现有 PIL 渲染逻辑并新增 HTML 截图渲染器。`handle_algo()` 自动检测文本是否含公式/代码块，路由到对应渲染器。HTML 模板通过 CDN 加载 KaTeX 和 highlight.js，用 Playwright 截图后返回图片字节。

**Tech Stack:** Python 3, PIL/Pillow, Playwright (Python), KaTeX (CDN), highlight.js (CDN), Jinja2, Node.js v18

**当前问题诊断：**
- `算法` 指令仅将文本传给 LLM 聊天回复，不渲染公式/代码
- `text_to_tactical_board()` 用 PIL 画图，不支持 LaTeX 公式和代码语法高亮
- `arteta_chat.py` 和 `arteta_standings.py` 各有一份重复的 `text_to_tactical_board()`

---

### Task 1: 创建共享渲染模块 `plugins/arteta_render.py`

**Files:**
- Create: `plugins/arteta_render.py`
- Delete (after migration): 从 `arteta_chat.py:133-949` 和 `arteta_standings.py:29-123` 中移除重复的 `text_to_tactical_board()` 及相关函数

- [ ] **Step 1: 从 arteta_chat.py 提取 PIL 渲染代码到新模块**

将 `arteta_chat.py` 中的以下函数和常量迁移到新文件 `plugins/arteta_render.py`：
- `FONT_PATH = "msyh.ttc"` (常量)
- `text_to_tactical_board(text: str) -> bytes` 完整函数
- `split_text_to_lines(text, font, max_width)` 辅助函数
- 必要的 import 语句

新文件内容：

```python
# plugins/arteta_render.py
import re
import io
from PIL import Image, ImageDraw, ImageFont
from pilmoji import Pilmoji

FONT_PATH = "msyh.ttc"

def split_text_to_lines(text: str, font: ImageFont.FreeTypeFont, max_width: int):
    lines = []
    for paragraph in text.split('\n'):
        if not paragraph.strip():
            lines.append("")
            continue
        current_line = ""
        for char in paragraph:
            test_line = current_line + char
            if font.getlength(test_line) <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = char
        if current_line:
            lines.append(current_line)
    return lines


def text_to_tactical_board(text: str) -> bytes:
    text = text.replace('*', '').replace('#', '')
    text = re.sub(r'^\s*[-+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)

    CANVAS_WIDTH = 1000
    PADDING = 60
    HEADER_HEIGHT = 120
    LINE_SPACING = 30

    try:
        font = ImageFont.truetype(FONT_PATH, 45)
        title_font = ImageFont.truetype(FONT_PATH, 55)
    except IOError:
        font = ImageFont.load_default()
        title_font = font

    max_text_width = CANVAS_WIDTH - 2 * PADDING
    wrapped_lines = []

    for paragraph in text.split('\n'):
        if not paragraph.strip():
            wrapped_lines.append([])
            continue
        if paragraph.strip() == '---':
            wrapped_lines.append([{"text": "---", "color": None}])
            continue
        parts = re.split(r'(\[blue\].*?\[/blue\]|\[red\].*?\[/red\])', paragraph)
        chunks = []
        for part in parts:
            if not part:
                continue
            if part.startswith('[blue]') and part.endswith('[/blue]'):
                chunks.append({"text": part[6:-7], "color": (2, 132, 199)})
            elif part.startswith('[red]') and part.endswith('[/red]'):
                chunks.append({"text": part[5:-6], "color": (220, 38, 38)})
            else:
                chunks.append({"text": part, "color": (30, 41, 59)})

        current_line = []
        current_x = 0
        for chunk in chunks:
            temp_str = ""
            color = chunk["color"]
            for char in chunk["text"]:
                if font.getlength(temp_str + char) + current_x <= max_text_width:
                    temp_str += char
                else:
                    if temp_str:
                        current_line.append({"text": temp_str, "color": color})
                    wrapped_lines.append(current_line)
                    current_line = []
                    current_x = 0
                    temp_str = char
            if temp_str:
                current_line.append({"text": temp_str, "color": color})
                current_x += font.getlength(temp_str)
        if current_line:
            wrapped_lines.append(current_line)

    bbox = font.getbbox("Tg")
    line_height = bbox[3] - bbox[1] + LINE_SPACING
    img_height = len(wrapped_lines) * line_height + HEADER_HEIGHT + PADDING * 2

    img = Image.new('RGB', (CANVAS_WIDTH, int(max(400, img_height))), color=(248, 250, 252))
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, CANVAS_WIDTH, 15], fill=(219, 0, 7))
    draw.text((PADDING, 45), "PREMIER LEAGUE | SITUATION ROOM", font=title_font, fill=(219, 0, 7))

    with Pilmoji(img) as pilmoji:
        draw.line([(PADDING, 115), (CANVAS_WIDTH - PADDING, 115)], fill=(203, 213, 225), width=3)
        y_text = HEADER_HEIGHT + 30
        for line_segments in wrapped_lines:
            if not line_segments:
                y_text += line_height
                continue
            if len(line_segments) == 1 and line_segments[0]["text"] == '---':
                draw.line([(PADDING, y_text + line_height // 2), (CANVAS_WIDTH - PADDING, y_text + line_height // 2)], fill=(230, 230, 230), width=2)
                y_text += line_height
                continue
            current_x = PADDING
            for segment in line_segments:
                pilmoji.text((current_x, y_text), segment["text"], font=font, fill=segment["color"])
                current_x += font.getlength(segment["text"])
            y_text += line_height

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG', quality=95)
    return img_byte_arr.getvalue()
```

- [ ] **Step 2: 创建 HTML 渲染模板 `templates/arteta_render.html`**

新建 `templates/arteta_render.html`，包含：
- KaTeX CSS/JS（CDN 加载）
- highlight.js（CDN 加载）
- 战术板风格 CSS（保持与现有图片风格一致）
- 自动渲染 `$...$` / `$$...$$` 公式
- 自动高亮 `<pre><code>` 代码块

```html
<!doctype html>
<html>
<head>
    <meta charset="utf-8"/>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/styles/github-dark.min.css">
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/contrib/auto-render.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/lib/common.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #f8fafc;
            color: #1e293b;
            font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            font-size: 28px;
            line-height: 1.6;
            padding: 40px 50px;
            width: 1000px;
        }
        .topbar {
            background: #db0007;
            height: 15px;
            width: 100%;
            margin-bottom: 30px;
        }
        .header {
            font-size: 38px;
            font-weight: 900;
            color: #db0007;
            margin-bottom: 20px;
            letter-spacing: 1px;
        }
        .separator {
            border: none;
            border-top: 3px solid #cbd5e1;
            margin: 20px 0;
        }
        h1, h2, h3 {
            color: #1e293b;
            margin-top: 1.2em;
            margin-bottom: 0.5em;
            font-weight: 700;
        }
        h1 { font-size: 1.6em; }
        h2 { font-size: 1.3em; }
        h3 { font-size: 1.1em; }
        p { margin: 0.8em 0; }
        strong { color: #db0007; font-weight: 700; }
        /* KaTeX 公式 */
        .katex { font-size: 1.1em; }
        /* 代码块 */
        pre {
            background: #0d1117;
            border-radius: 8px;
            padding: 20px;
            margin: 15px 0;
            overflow-x: auto;
            border: 1px solid #30363d;
        }
        pre code {
            font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
            font-size: 22px;
            line-height: 1.5;
            text-shadow: none;
            background: none;
            padding: 0;
        }
        code:not(pre code) {
            background: #e8e8e8;
            padding: 2px 8px;
            border-radius: 4px;
            font-family: 'Consolas', monospace;
            font-size: 0.9em;
        }
        blockquote {
            border-left: 5px solid #db0007;
            padding: 10px 20px;
            margin: 15px 0;
            background: #f1f5f9;
            border-radius: 0 8px 8px 0;
        }
        table {
            border-collapse: collapse;
            width: 100%;
            margin: 15px 0;
        }
        th, td {
            border: 1px solid #cbd5e1;
            padding: 10px 15px;
            text-align: left;
        }
        th { background: #db0007; color: white; font-weight: 700; }
        tr:nth-child(even) { background: #f1f5f9; }
        .arsenal-red { color: #db0007; font-weight: 700; }
        .arsenal-blue { color: #0284c7; font-weight: 700; }
    </style>
</head>
<body>
    <div class="topbar"></div>
    <div class="header">ARSENAL | TACTICAL BOARD</div>
    <hr class="separator">
    <div id="content"></div>
    <script>
        var raw = `{{ text | safe }}`;
        // 保护公式不被 marked 破坏
        var hasMath = raw.indexOf('$') !== -1;
        if (hasMath) {
            var blocks = [];
            var processed = raw
                .replace(/\$\$([\s\S]+?)\$\$/g, function(m) { blocks.push(m); return 'MATHBLOCK' + (blocks.length - 1) + 'END'; })
                .replace(/\$([\s\S]+?)\$/g, function(m) { blocks.push(m); return 'MATHBLOCK' + (blocks.length - 1) + 'END'; });
            var html = marked.parse(processed);
            blocks.forEach(function(b, i) { html = html.replace('MATHBLOCK' + i + 'END', function() { return b; }); });
            document.getElementById('content').innerHTML = html;
        } else {
            document.getElementById('content').innerHTML = marked.parse(raw);
        }
        try {
            if (window.renderMathInElement) {
                renderMathInElement(document.getElementById('content'), {
                    delimiters: [
                        { left: '$$', right: '$$', display: true },
                        { left: '$', right: '$', display: false }
                    ],
                    throwOnError: false,
                    errorColor: "#db0007"
                });
            }
        } catch(e) { console.error(e); }
        try { hljs.highlightAll(); } catch(e) {}
        document.body.setAttribute('data-rendered', '1');
        window.__RENDERED__ = true;
    </script>
</body>
</html>
```

- [ ] **Step 3: 在 `arteta_render.py` 中添加 HTML 渲染器**

在 `arteta_render.py` 末尾添加 `html_to_image()` 函数：

```python
import os
import jinja2
import asyncio

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
TEMPLATE_FILE = "arteta_render.html"

# 全局 Playwright 浏览器实例（复用，避免每次启动 Chromium）
_playwright_browser = None

def _get_template_env():
    loader = jinja2.FileSystemLoader(TEMPLATE_DIR)
    env = jinja2.Environment(loader=loader, autoescape=False)
    return env


async def _get_browser():
    """获取或创建全局 Playwright 浏览器实例"""
    global _playwright_browser
    if _playwright_browser is None or not _playwright_browser.is_connected():
        from playwright.async_api import async_playwright
        p = await async_playwright().start()
        _playwright_browser = await p.chromium.launch(headless=True)
    return _playwright_browser


async def html_to_image(markdown_text: str) -> bytes:
    """将 Markdown 文本渲染为图片（支持 KaTeX 公式 + 代码高亮）"""
    env = _get_template_env()
    template = env.get_template(TEMPLATE_FILE)
    html_content = template.render(text=markdown_text)

    browser = await _get_browser()
    page = await browser.new_page(
        viewport={"width": 1000, "height": 800},
        device_scale_factor=2  # Retina 清晰度
    )
    try:
        await page.set_content(html_content, wait_until="networkidle")
        # 等待 KaTeX 和 marked 渲染完成
        await page.wait_for_function("window.__RENDERED__ === true", timeout=15000)
        # 额外等待公式渲染（异步）
        await asyncio.sleep(0.5)

        # 计算实际内容高度
        content_height = await page.evaluate("document.body.scrollHeight")
        await page.set_viewport_size({"width": 1000, "height": content_height})

        screenshot = await page.screenshot(
            type="png",
            full_page=True,
            quality=95
        )
        return screenshot
    finally:
        await page.close()


async def close_browser():
    """关闭 Playwright 浏览器（用于 bot 退出时清理）"""
    global _playwright_browser
    if _playwright_browser:
        await _playwright_browser.close()
        _playwright_browser = None


def needs_html_render(text: str) -> bool:
    """检测文本是否包含需要 HTML 渲染的内容（公式或代码块）"""
    return '$' in text or '```' in text or '    ' in text
```

- [ ] **Step 4: 本地验证模块加载正常**

```bash
cd /opt/arteta_bot
python3 -c "from plugins.arteta_render import text_to_tactical_board, html_to_image, needs_html_render; print('render module OK')"
```

Expected: `render module OK`

---

### Task 2: 服务器安装 Playwright + Chromium

- [ ] **Step 1: 安装 playwright Python 包**

```bash
ssh arteta "cd /opt/arteta_bot && source venv/bin/activate && pip install playwright"
```

- [ ] **Step 2: 安装 Chromium 浏览器**

```bash
ssh arteta "cd /opt/arteta_bot && source venv/bin/activate && python3 -m playwright install chromium"
```

- [ ] **Step 3: 验证安装成功**

```bash
ssh arteta "cd /opt/arteta_bot && source venv/bin/activate && python3 -c 'from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(headless=True); b.close(); p.stop(); print(\"playwright OK\")'"
```

Expected: `playwright OK`

---

### Task 3: 在 `arteta_chat.py` 中集成新渲染器

- [ ] **Step 1: 替换 import 和渲染调用**

在 `arteta_chat.py` 顶部将 PIL 相关 import 替换为从 `arteta_render` 导入：

```python
# 替换这一行：
# from PIL import Image, ImageDraw, ImageFont
# import io
# from pilmoji import Pilmoji

# 改为：
from plugins.arteta_render import (
    text_to_tactical_board,
    html_to_image,
    needs_html_render,
    close_browser as close_render_browser,
)
```

- [ ] **Step 2: 删除 arteta_chat.py 中旧的 `text_to_tactical_board()` 和 `split_text_to_lines()`**

删除从 `split_text_to_lines` 函数定义开始到 `text_to_tactical_board` 函数结尾的整段代码（原文件约 133-949 行，删除重复代码）。

- [ ] **Step 3: 修改 `handle_algo()` 使用 HTML 渲染器**

将 `handle_algo()`（约 1239-1252 行）修改为：

```python
@algo_cmd.handle()
async def handle_algo(bot: Bot, event: MessageEvent):
    raw_text = event.get_message().extract_plain_text().strip()
    for cmd in ["算法", "代码", "leetcode", "战术演练", "算法题"]:
        if raw_text.startswith(cmd):
            raw_text = raw_text[len(cmd):].strip()
            break

    if not raw_text:
        await algo_cmd.finish("把你需要解决的问题写在白板上！")
        return

    # 先让 AI 以阿尔特塔风格回答
    algo_prompt = (
        f"【技术指导】对方提交了技术问题，用教练指导球员口头说话的方式解答，"
        f"如果涉及代码，用 ``` 代码块包裹展示；如果涉及数学公式，用 $...$ 或 $$...$$ 展示。"
        f"绝对不要加小标题和列表符：\n{raw_text}"
    )
    await process_chat(bot, event, custom_prompt=algo_prompt)
```

注意：`process_chat()` 内部已有对 AI 回复的图片渲染。需要在 `process_chat()` 中插入判断：如果 AI 回复包含公式/代码，则使用 `html_to_image()` 代替 `text_to_tactical_board()`。

- [ ] **Step 4: 修改 `process_chat()` 的图片渲染分支**

找到 `process_chat()` 中调用 `text_to_tactical_board()` 的位置，添加自动检测与路由：

```python
# 在 process_chat() 中，构建完 final_reply 后：
# 原来：img_bytes = text_to_tactical_board(final_reply)
# 改为：
if needs_html_render(final_reply):
    try:
        img_bytes = await html_to_image(final_reply)
    except Exception:
        img_bytes = text_to_tactical_board(final_reply)
else:
    img_bytes = text_to_tactical_board(final_reply)
```

- [ ] **Step 5: 添加 bot 退出时的浏览器清理**

在文件末尾添加 nonebot 的 shutdown 事件处理：

```python
# 在 arteta_chat.py 末尾添加
from nonebot import get_driver

@get_driver().on_shutdown
async def cleanup():
    await close_render_browser()
```

- [ ] **Step 6: 修改 `arteta_standings.py` 使用共享渲染模块**

将 `arteta_standings.py` 中顶部的 import 替换为从 `arteta_render` 导入，删除其自身的 `text_to_tactical_board()` 重复代码。

```python
# 在 arteta_standings.py 顶部添加
from plugins.arteta_render import text_to_tactical_board
# 然后删除其自身定义的所有绘图函数（约 29-123 行）
```

---

### Task 4: 部署与验证

- [ ] **Step 1: 上传所有修改到服务器**

```bash
scp D:/Users/zty/arteta_bot/plugins/arteta_render.py arteta:/opt/arteta_bot/plugins/arteta_render.py
scp D:/Users/zty/arteta_bot/plugins/arteta_chat.py arteta:/opt/arteta_bot/plugins/arteta_chat.py
scp D:/Users/zty/arteta_bot/plugins/arteta_standings.py arteta:/opt/arteta_bot/plugins/arteta_standings.py
scp -r D:/Users/zty/arteta_bot/templates arteta:/opt/arteta_bot/templates
```

- [ ] **Step 2: 重启机器人**

```bash
ssh arteta "supervisorctl restart arteta_bot"
```

- [ ] **Step 3: 查看启动日志确认插件加载正常**

```bash
ssh arteta "supervisorctl tail arteta_bot"
```

- [ ] **Step 4: 发送测试消息验证**

在 QQ 群中发送：
- `/算法 用Python写一个斐波那契数列` — 验证代码高亮
- `/算法 求解二次方程 ax^2+bx+c=0，公式是什么？` — 验证公式渲染
- `@bot 用泰勒展开证明e^x的极限` — 验证自动检测路由

---

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 截图引擎 | Playwright (Python) | 与 astrbot 一致，Node.js 已安装，纯 Python 生态 |
| 公式引擎 | KaTeX (CDN) | 比 MathJax 快 10x，无需服务端 LaTeX 发行版 |
| 代码高亮 | highlight.js | 轻量，自动语言检测，CDN 加载无依赖 |
| Markdown 解析 | marked | 轻量快速，与 KaTeX 配合成熟 |
| 渲染策略 | 自动检测（`$` / ```） | 无需用户手动指定渲染模式 |
| 模块结构 | 共享 `arteta_render.py` | 消除 `arteta_chat.py` 和 `arteta_standings.py` 的重复代码 |
| 浏览器复用 | 全局单例 | 避免每次请求启动 Chromium（~2s 启动时间） |
| 分辨率 | device_scale_factor=2 | Retina 清晰度，与现有 PIL 图片质量一致 |

## Rollback 方案

如果渲染出现问题，回滚步骤：
1. 还原 `arteta_chat.py` 和 `arteta_standings.py` 到旧版本
2. 删除 `arteta_render.py`
3. 重启服务

```bash
ssh arteta "supervisorctl stop arteta_bot"
# 回滚文件...
ssh arteta "supervisorctl start arteta_bot"
```
