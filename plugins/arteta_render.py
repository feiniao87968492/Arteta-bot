# plugins/arteta_render.py
import re
import io
import os
import jinja2
import asyncio
import logging
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont
from pilmoji import Pilmoji

logger = logging.getLogger(__name__)

FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "msyh.ttc")
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
TEMPLATE_FILE = "arteta_render.html"

# 全局 Playwright 实例和浏览器（复用，避免每次启动 Chromium）
_playwright = None
_playwright_browser = None

# 缓存的 Jinja2 环境
_TEMPLATE_ENV = None


def _get_template_env():
    global _TEMPLATE_ENV
    if _TEMPLATE_ENV is None:
        loader = jinja2.FileSystemLoader(TEMPLATE_DIR)
        _TEMPLATE_ENV = jinja2.Environment(loader=loader, autoescape=False)
    return _TEMPLATE_ENV


async def _get_browser():
    global _playwright, _playwright_browser
    if _playwright_browser is None or not _playwright_browser.is_connected():
        if _playwright:
            await _playwright.stop()
        from playwright.async_api import async_playwright
        _playwright = await async_playwright().start()
        _playwright_browser = await _playwright.chromium.launch(headless=True)
    return _playwright_browser


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

    CANVAS_WIDTH = 1500
    PADDING = 80
    HEADER_HEIGHT = 120
    LINE_SPACING = 30

    try:
        font = ImageFont.truetype(FONT_PATH, 45)
        title_font = ImageFont.truetype(FONT_PATH, 55)
    except IOError:
        logger.warning(f"字体文件 {FONT_PATH} 未找到，使用 PIL 默认字体（输出质量会严重下降）")
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


async def html_to_image(markdown_text: str) -> bytes:
    """将 Markdown 文本渲染为图片（支持 KaTeX 公式 + 代码高亮）"""
    markdown_text = normalize_math_delimiters(markdown_text)
    env = _get_template_env()
    template = env.get_template(TEMPLATE_FILE)
    html_content = template.render(text=markdown_text)

    browser = await _get_browser()
    page = await browser.new_page(
        viewport={"width": 1500, "height": 800},
        device_scale_factor=2
    )
    try:
        await page.set_content(html_content, wait_until="networkidle", timeout=15000)
        await page.wait_for_function("window.__RENDERED__ === true", timeout=15000)
        await asyncio.sleep(0.5)

        content_height = await page.evaluate("document.body.scrollHeight")
        await page.set_viewport_size({"width": 1500, "height": content_height})

        screenshot = await page.screenshot(
            type="png",
            full_page=True
        )
        return screenshot
    finally:
        await page.close()


def _get_chinese_font():
    """获取中文字体路径"""
    font_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "msyh.ttc")
    if os.path.exists(font_path):
        return font_path
    for p in ["C:/Windows/Fonts/msyh.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
              "/home/arteta/.fonts/msyh.ttc", "/opt/arteta_bot/msyh.ttc"]:
        if os.path.exists(p):
            return p
    return None


def favorability_bar_chart(data: list, title: str = "信任度排行", bar_color: tuple = (0.859, 0.0, 0.027)) -> bytes:
    """绘制横向柱状图。data 为 [(nickname, favorability, level, user_id), ...]"""
    # 临时关闭 LaTeX 渲染（arteta_cmath.py 全局设了 usetex=True，会与中文冲突）
    _old_usetex = plt.rcParams.get('text.usetex', False)
    plt.rcParams['text.usetex'] = False
    try:
        return _do_bar_chart(data, title, bar_color)
    finally:
        plt.rcParams['text.usetex'] = _old_usetex


def _do_bar_chart(data: list, title: str, bar_color: tuple) -> bytes:
    from matplotlib.font_manager import FontProperties

    font_path = _get_chinese_font()
    font_prop = FontProperties(fname=font_path) if font_path else None

    # 反转：数据从 DB 按降序查出，最高排第一。反转后最高在图表顶部显示
    data = list(reversed(data))

    n = len(data)
    fig_height = max(3, n * 0.55)
    fig, ax = plt.subplots(figsize=(14, fig_height))
    fig.patch.set_facecolor('#F8FAFC')
    ax.set_facecolor('#F8FAFC')

    names, values, levels, colors = [], [], [], []
    for item in data:
        if len(item) == 4:
            nickname, fav, level, user_id = item
        else:
            nickname, fav, level = item
            user_id = ""
        # 不截断昵称，留给 tight_layout + left margin 处理显示空间
        display_name = nickname
        names.append(display_name)
        values.append(fav)
        levels.append(level)
        colors.append('#F59E0B' if user_id == '2648955710' else bar_color)

    y_pos = range(n)

    # 绘制横向柱状图
    ax.barh(y_pos, values, height=0.6, color=colors, edgecolor='white', linewidth=0.5)

    # 右侧标注数值和等级
    max_val = max(abs(v) for v in values)
    offset = max_val * 0.02 if max_val > 0 else 1
    for i, (v, lvl) in enumerate(zip(values, levels)):
        label = f"{v}  ({lvl})"
        ax.text(v + offset if v >= 0 else v - offset * 3,
                i, label, va='center', fontsize=11, color='#1E293B',
                fontproperties=font_prop)

    # Y 轴标签
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=12, color='#1E293B')
    if font_prop:
        for label in ax.get_yticklabels():
            label.set_fontproperties(font_prop)

    # 给左侧昵称和右侧数值留空间，不用 tight_layout 以避免与 subplots_adjust 冲突
    max_name_len = max((len(n) for n in names), default=0)
    left_margin = max(0.12, 0.12 + (max_name_len - 10) * 0.015)
    fig.subplots_adjust(left=left_margin, right=0.92)

    # 隐藏上/右边框
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#CBD5E1')
    ax.spines['bottom'].set_color('#CBD5E1')

    # X 轴网格线
    ax.xaxis.grid(True, alpha=0.3, color='#CBD5E1')
    ax.set_axisbelow(True)

    # 标题 + 装饰红线
    if font_prop:
        ax.text(0.5, 1.08, title, transform=ax.transAxes, ha='center', va='bottom',
                fontsize=20, fontweight='bold', color='#DB0007', fontproperties=font_prop)
    else:
        ax.text(0.5, 1.08, title, transform=ax.transAxes, ha='center', va='bottom',
                fontsize=20, fontweight='bold', color='#DB0007')
    ax.plot([0, 1], [1.04, 1.04], transform=ax.transAxes, color='#DB0007', linewidth=3, clip_on=False)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


async def close_browser():
    global _playwright, _playwright_browser
    if _playwright_browser:
        await _playwright_browser.close()
        _playwright_browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None


def normalize_math_delimiters(text: str) -> str:
    """将 \\(...\\) 和 \\[...\\] 统一为 $...$ 和 $$...$$（KaTeX 只认 $ 定界符）"""
    # 用拼接方式避免 Python 3.13 Windows 上 r"\\\[" 吃掉反斜杠的 tokenizer bug
    _BS = chr(92)
    text = re.sub(_BS + _BS + _BS + "[" + r"([\s\S]*?)" + _BS + _BS + _BS + "]", r'$$\1$$', text)
    text = re.sub(_BS + _BS + _BS + "(" + r"([\s\S]*?)" + _BS + _BS + _BS + ")", r'$\1$', text)
    return text


def needs_html_render(text: str) -> bool:
    """检测文本是否包含需要 HTML 渲染的内容（公式或代码块）"""
    text = normalize_math_delimiters(text)
    if '```' in text:
        return True
    if re.search(r'\$[^$]+\$', text):
        return True
    if re.search(r'(?m)^    ', text):
        return True
    return False
