# URL 自动解析与评价功能 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 群聊中检测到 URL 时自动抓取网页内容，以阿尔特塔口吻评价后图片回复

**Architecture:** 新建 `plugins/arteta_url.py`，通过 `on_message` 监听群消息，正则检测 URL，httpx 抓取，BeautifulSoup 提取摘要，调用 DeepSeek 评价，渲染为图片回复

**Tech Stack:** NoneBot2 + OneBot v11, httpx, BeautifulSoup4, lxml, Pillow, Pilmoji

---

### Task 1: 更新依赖配置

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 添加 beautifulsoup4 和 lxml 到依赖**

```toml
dependencies = [
    "nonebot2",
    "nonebot-adapter-onebot",
    "nonebot-plugin-apscheduler",
    "httpx",
    "aiosqlite",
    "pillow",
    "pilmoji",
    "duckduckgo_search",
    "beautifulsoup4",
    "lxml",
]
```

- [ ] **Step 2: 安装新依赖**

Run: `cd /d D:\Users\zty\arteta_bot && venv\bin\python -m pip install beautifulsoup4 lxml`
Expected: 安装成功

- [ ] **Step 3: 提交**

```bash
git add pyproject.toml
git commit -m "chore: add beautifulsoup4 and lxml dependencies"
```

---

### Task 2: 创建 URL 解析插件

**Files:**
- Create: `plugins/arteta_url.py`

`plugins/arteta_url.py` 包含：

1. **URL 检测** - 正则匹配群消息中的 `https?://` 链接
2. **网页抓取** - httpx 获取页面内容（15s 超时，跟踪重定向）
3. **内容提取** - BeautifulSoup 提取 title、meta description、正文前 2000 字
4. **评价生成** - 调用 DeepSeek，以阿尔特塔口吻点评
5. **图片回复** - 复用 `text_to_tactical_board` 渲染为图片

**模块加载注意事项：**
- 从 `arteta_chat` 导入 `text_to_tactical_board`（该模块在插件加载时已初始化）
- 通过 `nonebot.get_driver().config` 获取 `deepseek_api_key`
- 使用 `on_message` 处理器，`priority=12, block=False`

- [ ] **Step 1: 创建 `plugins/arteta_url.py`**

```python
import nonebot
from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
import httpx
import re
from bs4 import BeautifulSoup
import io
from PIL import Image, ImageDraw, ImageFont
from pilmoji import Pilmoji

# --- 配置 ---
driver = nonebot.get_driver()
try:
    config = driver.config.model_dump()
except AttributeError:
    config = driver.config.dict()

DEEPSEEK_KEY = str(config.get("deepseek_api_key", "")).strip('"\'')
FONT_PATH = "msyh.ttc"

# URL 正则
URL_PATTERN = re.compile(r'https?://[^\s]+')

# 消息处理器：匹配任意含 URL 的群消息
url_matcher = on_message(priority=12, block=False)

# --- 网页抓取与内容提取 ---
async def fetch_url_content(url: str) -> dict:
    """抓取网页并提取标题、描述、正文摘要"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            meta_desc = ""
            meta = soup.find("meta", attrs={"name": "description"})
            if meta and meta.get("content"):
                meta_desc = meta["content"].strip()

            # 提取正文文本（取前 2000 字）
            body_text = ""
            for tag in soup.find_all(["p", "div", "article", "section"]):
                text = tag.get_text(strip=True)
                if len(text) > 30:  # 跳过短文本
                    body_text += text + "\n"
                    if len(body_text) >= 2000:
                        body_text = body_text[:2000]
                        break

            return {
                "title": title,
                "description": meta_desc,
                "body": body_text.strip(),
            }
    except Exception as e:
        print(f"[URL Fetch Error] {url}: {e}")
        return None


# --- 文本渲染为战术板图片 ---
def text_to_tactical_board(text: str) -> bytes:
    """将文本渲染为阿森纳战术板风格的图片"""
    text = text.replace('*', '').replace('#', '')
    text = re.sub(r'^\s*[-+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)

    CANVAS_WIDTH = 2000
    PADDING = 60
    HEADER_HEIGHT = 120
    LINE_SPACING = 25

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
    draw.text((PADDING, 45), "ARSENAL FC | LINK SCOUT", font=title_font, fill=(219, 0, 7))

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


# --- 调用 DeepSeek 评价 ---
URL_PROMPT = (
    "【最高指令】：你是阿森纳主帅米克尔·阿尔特塔。\n"
    "有人分享了一个链接，你的工作是快速浏览内容并给出你的点评。\n"
    "要求：\n"
    "1. 用主教练的口吻，简洁有力（100-200字），就像在更衣室里对球员训话。\n"
    "2. 先概括这是什么内容，再给出你的看法——好在哪里、差在哪里、对球队有什么启发。\n"
    "3. 必须有立场，不要含糊。\n"
    "4. 纯中文，严禁列表符号和标题。"
)


async def evaluate_url(title: str, description: str, body: str, url: str) -> str:
    """调用 DeepSeek 评价链接内容"""
    content = f"标题：{title}\n"
    if description:
        content += f"描述：{description}\n"
    if body:
        content += f"正文摘要：{body[:1500]}\n"
    content += f"链接：{url}"

    messages = [
        {"role": "system", "content": URL_PROMPT},
        {"role": "user", "content": f"看看这个小伙子分享的东西，点评一下：\n\n{content}"},
    ]

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
                json={"model": "deepseek-v4-flash", "messages": messages},
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            else:
                print(f"[DeepSeek URL Error] {resp.status_code}")
                return ""
    except Exception as e:
        print(f"[DeepSeek URL Exception] {e}")
        return ""


# --- 主处理器 ---
@url_matcher.handle()
async def handle_url(bot: Bot, event: GroupMessageEvent):
    text = event.get_plaintext().strip()
    urls = URL_PATTERN.findall(text)
    if not urls:
        return

    # 只处理第一个 URL
    url = urls[0]

    # 抓取网页
    page_data = await fetch_url_content(url)
    if not page_data:
        return  # 静默忽略抓取失败

    # 调用 DeepSeek 评价
    evaluation = await evaluate_url(
        page_data.get("title", ""),
        page_data.get("description", ""),
        page_data.get("body", ""),
        url,
    )
    if not evaluation:
        return  # 静默忽略评价失败

    # 渲染为图片回复
    img_bytes = text_to_tactical_board(evaluation)
    await url_matcher.send(MessageSegment.image(img_bytes))
```

- [ ] **Step 2: 验证插件语法正确**

Run: `cd /d D:\Users\zty\arteta_bot && venv\bin\python -c "import py_compile; py_compile.compile('plugins/arteta_url.py', doraise=True)"`
Expected: 无错误输出

- [ ] **Step 3: 验证依赖安装成功**

Run: `cd /d D:\Users\zty\arteta_bot && venv\bin\python -c "from bs4 import BeautifulSoup; print('OK')"`
Expected: `OK`

- [ ] **Step 4: 提交**

```bash
git add plugins/arteta_url.py
git commit -m "feat: add auto URL parser and evaluator"
```

---

### 自审检查

1. **Spec 覆盖:** 设计文档中所有要求均已覆盖：自动触发、URL 正则检测、网页抓取、内容提取、DeepSeek 评价、阿尔特塔口吻、图片回复、错误静默忽略
2. **无占位符:** 所有代码块包含完整的可运行代码
3. **类型一致性:** 函数名和签名在单个文件中保持自洽
4. **依赖完整性:** Task 1 添加依赖，Task 2 创建插件
