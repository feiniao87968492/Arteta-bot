# plugins/arteta_render.py
import re
import io
import os
import html
import base64
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
HEADER_IMAGE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "assets",
    "render",
    "situation_room_header.png",
)

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


STYLE_TAG_RE = re.compile(r'\[(/?)(blue|red|bold|large|color|scale)(?:=([^\]]+))?\]')
SPAN_STYLE_RE = re.compile(r'<span\s+style=["\']([^"\']*)["\']\s*>(.*?)</span>', re.I | re.S)
SPAN_CLASS_RE = re.compile(r'<span\s+class=["\']([^"\']*)["\']\s*>(.*?)</span>', re.I | re.S)
HTML_TAG_RE = re.compile(r'<[^>]+>')
DEFAULT_TEXT_COLOR = (30, 41, 59)
STYLE_COLORS = {
    "blue": (2, 132, 199),
    "red": (220, 38, 38),
}
NAMED_STYLE_COLORS = {
    "black": (17, 24, 39),
    "white": (255, 255, 255),
    "red": (219, 0, 7),
    "blue": (2, 132, 199),
    "green": (22, 163, 74),
    "gold": (215, 191, 106),
    "yellow": (202, 138, 4),
    "orange": (234, 88, 12),
    "purple": (147, 51, 234),
    "pink": (219, 39, 119),
}


def _normalize_css_color(value: str) -> str:
    color = str(value or "").strip().lower()
    if color in NAMED_STYLE_COLORS:
        return color
    if color.startswith("#"):
        raw = color[1:]
        if len(raw) in (3, 6) and all(ch in "0123456789abcdef" for ch in raw):
            return color
    return ""


def _color_to_rgb(value: str):
    color = _normalize_css_color(value)
    if not color:
        return DEFAULT_TEXT_COLOR
    if color in NAMED_STYLE_COLORS:
        return NAMED_STYLE_COLORS[color]
    raw = color[1:]
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    return tuple(int(raw[index:index + 2], 16) for index in (0, 2, 4))


def _normalize_scale(value, default: float = 1.0) -> float:
    try:
        scale = float(str(value or "").strip().lower().rstrip("x"))
    except Exception:
        return default
    return scale if scale > 0 else default


def _format_scale(value) -> str:
    return "{0:g}".format(_normalize_scale(value))


def _style_wrappers_from_css(style: str) -> list:
    compact = re.sub(r"\s+", "", str(style or "").lower())
    wrappers = []
    if "color:red" in compact or "color:#db0007" in compact or "color:#dc2626" in compact:
        wrappers.append(("[red]", "[/red]"))
    elif "color:blue" in compact or "color:#0284c7" in compact:
        wrappers.append(("[blue]", "[/blue]"))
    else:
        color_match = re.search(r"color:([^;]+)", compact)
        if color_match:
            color = _normalize_css_color(color_match.group(1))
            if color:
                wrappers.append(("[color={0}]".format(color), "[/color]"))
    if "font-weight:bold" in compact or "font-weight:700" in compact or "font-weight:800" in compact:
        wrappers.append(("[bold]", "[/bold]"))
    size_match = re.search(r"font-size:(\d+(?:\.\d+)?)px", compact)
    if size_match:
        size = float(size_match.group(1))
        if size >= 56:
            wrappers.append(("[scale={0}]".format(_format_scale(size / 28.0)), "[/scale]"))
        elif size >= 18:
            wrappers.append(("[large]", "[/large]"))
    return wrappers


def _style_wrappers_from_class(class_name: str) -> list:
    classes = set(str(class_name or "").lower().split())
    wrappers = []
    if "arsenal-red" in classes:
        wrappers.append(("[red]", "[/red]"))
    if "arsenal-blue" in classes:
        wrappers.append(("[blue]", "[/blue]"))
    if "arsenal-bold" in classes:
        wrappers.append(("[bold]", "[/bold]"))
    if "arsenal-large" in classes:
        wrappers.append(("[large]", "[/large]"))
    return wrappers


def _wrap_style_text(text: str, wrappers: list) -> str:
    result = text
    for start, end in reversed(wrappers):
        result = "{0}{1}{2}".format(start, result, end)
    return result


def normalize_inline_style_markup(text: str) -> str:
    def replace_style(match):
        wrappers = _style_wrappers_from_css(match.group(1))
        content = normalize_inline_style_markup(match.group(2))
        return _wrap_style_text(content, wrappers) if wrappers else content

    def replace_class(match):
        wrappers = _style_wrappers_from_class(match.group(1))
        content = normalize_inline_style_markup(match.group(2))
        return _wrap_style_text(content, wrappers) if wrappers else content

    normalized = SPAN_STYLE_RE.sub(replace_style, str(text or ""))
    normalized = SPAN_CLASS_RE.sub(replace_class, normalized)
    normalized = HTML_TAG_RE.sub("", normalized)
    return html.unescape(normalized)


def style_tags_to_html(text: str) -> str:
    normalized = normalize_inline_style_markup(text)
    normalized = normalized.replace("[red]", '<span class="arsenal-red">')
    normalized = normalized.replace("[/red]", '</span>')
    normalized = normalized.replace("[blue]", '<span class="arsenal-blue">')
    normalized = normalized.replace("[/blue]", '</span>')
    normalized = normalized.replace("[bold]", '<span class="arsenal-bold">')
    normalized = normalized.replace("[/bold]", '</span>')
    normalized = normalized.replace("[large]", '<span class="arsenal-large">')
    normalized = normalized.replace("[/large]", '</span>')
    normalized = re.sub(
        r'\[color=([^\]]+)\]',
        lambda match: '<span class="arsenal-custom-color" style="color: {0}">'.format(_normalize_css_color(match.group(1)) or "inherit"),
        normalized,
    )
    normalized = normalized.replace("[/color]", '</span>')
    normalized = re.sub(
        r'\[scale=([^\]]+)\]',
        lambda match: '<span class="arsenal-scale" style="font-size: {0}em">'.format(_format_scale(match.group(1))),
        normalized,
    )
    normalized = normalized.replace("[/scale]", '</span>')
    return normalized


def parse_inline_style_chunks(text: str) -> list:
    text = normalize_inline_style_markup(text)
    chunks = []
    state = {"color": DEFAULT_TEXT_COLOR, "bold": False, "large": False, "scale": 1.0}
    pos = 0
    for match in STYLE_TAG_RE.finditer(text):
        if match.start() > pos:
            chunks.append({
                "text": text[pos:match.start()],
                "color": state["color"],
                "bold": state["bold"],
                "large": state["large"],
                "scale": state["scale"],
            })
        closing, tag, value = match.groups()
        if tag in STYLE_COLORS:
            state["color"] = DEFAULT_TEXT_COLOR if closing else STYLE_COLORS[tag]
        elif tag == "bold":
            state["bold"] = not closing
        elif tag == "large":
            state["large"] = not closing
            state["scale"] = 1.2 if not closing else 1.0
        elif tag == "color":
            state["color"] = DEFAULT_TEXT_COLOR if closing else _color_to_rgb(value)
        elif tag == "scale":
            state["scale"] = 1.0 if closing else _normalize_scale(value)
            state["large"] = False
        pos = match.end()
    if pos < len(text):
        chunks.append({
            "text": text[pos:],
            "color": state["color"],
            "bold": state["bold"],
            "large": state["large"],
            "scale": state["scale"],
        })
    return [chunk for chunk in chunks if chunk["text"]]


def _font_for_chunk(chunk: dict, normal_font, large_font):
    scale = _normalize_scale(chunk.get("scale"), 1.0)
    if scale != 1.0 and hasattr(normal_font, "font_variant"):
        return normal_font.font_variant(size=max(1, int(normal_font.size * scale)))
    return large_font if chunk.get("large") else normal_font


def _draw_text(pilmoji, xy, text: str, font, fill, bold: bool = False):
    x, y = xy
    pilmoji.text((x, y), text, font=font, fill=fill)
    if bold:
        pilmoji.text((x + 1, y), text, font=font, fill=fill)


def _load_header_image(width: int):
    if not os.path.exists(HEADER_IMAGE_PATH):
        return None
    try:
        with Image.open(HEADER_IMAGE_PATH) as source:
            ratio = width / float(source.width)
            height = max(1, int(source.height * ratio))
            return source.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
    except Exception as exc:
        logger.warning("回复框顶部横幅加载失败: %s", exc)
        return None


def _header_image_data_uri() -> str:
    if not os.path.exists(HEADER_IMAGE_PATH):
        return ""
    try:
        with open(HEADER_IMAGE_PATH, "rb") as image_file:
            payload = base64.b64encode(image_file.read()).decode("ascii")
        return "data:image/png;base64,{0}".format(payload)
    except Exception as exc:
        logger.warning("回复框顶部横幅编码失败: %s", exc)
        return ""


def text_to_tactical_board(text: str) -> bytes:
    text = normalize_inline_style_markup(text)
    text = text.replace('*', '')
    text = re.sub(r'(?m)^\s{0,3}#{1,6}\s*', '', text)
    text = re.sub(r'^\s*[-+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)

    CANVAS_WIDTH = 1500
    FRAME_MARGIN = 32
    FRAME_TOP_GAP = 34
    OUTER_BORDER = 5
    RED_BORDER = 8
    GOLD_BORDER = 3
    FRAME_GAP = 9
    PAPER_PADDING_X = 58
    PAPER_PADDING_TOP = 54
    PAPER_PADDING_BOTTOM = 64
    CONTENT_X = FRAME_MARGIN + OUTER_BORDER + FRAME_GAP + RED_BORDER + FRAME_GAP + GOLD_BORDER + 7 + PAPER_PADDING_X
    CONTENT_RIGHT = CONTENT_X
    LINE_SPACING = 30
    header_image = _load_header_image(CANVAS_WIDTH)
    HEADER_HEIGHT = header_image.height if header_image else 120

    try:
        font = ImageFont.truetype(FONT_PATH, 45)
        large_font = ImageFont.truetype(FONT_PATH, 54)
        title_font = ImageFont.truetype(FONT_PATH, 55)
    except IOError:
        logger.warning(f"字体文件 {FONT_PATH} 未找到，使用 PIL 默认字体（输出质量会严重下降）")
        font = ImageFont.load_default()
        large_font = font
        title_font = font

    max_text_width = CANVAS_WIDTH - CONTENT_X - CONTENT_RIGHT
    wrapped_lines = []

    for paragraph in text.split('\n'):
        if not paragraph.strip():
            wrapped_lines.append([])
            continue
        if paragraph.strip() == '---':
            wrapped_lines.append([{"text": "---", "color": None}])
            continue
        chunks = parse_inline_style_chunks(paragraph)

        current_line = []
        current_x = 0
        for chunk in chunks:
            temp_str = ""
            color = chunk["color"]
            chunk_font = _font_for_chunk(chunk, font, large_font)
            for char in chunk["text"]:
                if chunk_font.getlength(temp_str + char) + current_x <= max_text_width:
                    temp_str += char
                else:
                    if temp_str:
                        current_line.append({
                            "text": temp_str,
                            "color": color,
                            "bold": chunk.get("bold", False),
                            "large": chunk.get("large", False),
                            "scale": chunk.get("scale", 1.0),
                        })
                    wrapped_lines.append(current_line)
                    current_line = []
                    current_x = 0
                    temp_str = char
            if temp_str:
                current_line.append({
                    "text": temp_str,
                    "color": color,
                    "bold": chunk.get("bold", False),
                    "large": chunk.get("large", False),
                    "scale": chunk.get("scale", 1.0),
                })
                current_x += chunk_font.getlength(temp_str)
        if current_line:
            wrapped_lines.append(current_line)

    def line_height_for(line_segments):
        fonts = [_font_for_chunk(segment, font, large_font) for segment in (line_segments or [{"large": False, "scale": 1.0}])]
        heights = []
        for item_font in fonts:
            bbox = item_font.getbbox("Tg")
            heights.append(bbox[3] - bbox[1])
        fallback_bbox = font.getbbox("Tg")
        return max(heights or [fallback_bbox[3] - fallback_bbox[1]]) + LINE_SPACING

    text_height = sum(line_height_for(line) for line in wrapped_lines)
    frame_top = HEADER_HEIGHT + FRAME_TOP_GAP
    paper_top = frame_top + OUTER_BORDER + FRAME_GAP + RED_BORDER + FRAME_GAP + GOLD_BORDER + 7
    y_start = paper_top + PAPER_PADDING_TOP
    frame_bottom = y_start + text_height + PAPER_PADDING_BOTTOM
    img_height = frame_bottom + FRAME_MARGIN

    img = Image.new('RGB', (CANVAS_WIDTH, int(max(520, img_height))), color=(216, 210, 198))
    draw = ImageDraw.Draw(img)

    if header_image:
        img.paste(header_image, (0, 0))
    else:
        draw.rectangle([0, 0, CANVAS_WIDTH, 15], fill=(219, 0, 7))
        draw.text((CONTENT_X, 45), "PREMIER LEAGUE | SITUATION ROOM", font=title_font, fill=(219, 0, 7))

    frame_left = FRAME_MARGIN
    frame_right = CANVAS_WIDTH - FRAME_MARGIN
    frame_outer = [frame_left, frame_top, frame_right, frame_bottom]
    draw.rectangle(frame_outer, fill=(253, 252, 247), outline=(15, 76, 129), width=OUTER_BORDER)

    red_rect = [
        frame_left + OUTER_BORDER + FRAME_GAP,
        frame_top + OUTER_BORDER + FRAME_GAP,
        frame_right - OUTER_BORDER - FRAME_GAP,
        frame_bottom - OUTER_BORDER - FRAME_GAP,
    ]
    draw.rectangle(red_rect, outline=(219, 0, 7), width=RED_BORDER)

    gold_rect = [
        red_rect[0] + RED_BORDER + FRAME_GAP,
        red_rect[1] + RED_BORDER + FRAME_GAP,
        red_rect[2] - RED_BORDER - FRAME_GAP,
        red_rect[3] - RED_BORDER - FRAME_GAP,
    ]
    draw.rectangle(gold_rect, outline=(215, 191, 106), width=GOLD_BORDER)

    paper_rect = [
        gold_rect[0] + GOLD_BORDER + 7,
        gold_rect[1] + GOLD_BORDER + 7,
        gold_rect[2] - GOLD_BORDER - 7,
        gold_rect[3] - GOLD_BORDER - 7,
    ]
    draw.rectangle(paper_rect, fill=(255, 254, 250), outline=(239, 227, 170), width=2)

    with Pilmoji(img) as pilmoji:
        if not header_image:
            draw.line([(CONTENT_X, 115), (CANVAS_WIDTH - CONTENT_RIGHT, 115)], fill=(203, 213, 225), width=3)
        y_text = y_start
        for line_segments in wrapped_lines:
            line_height = line_height_for(line_segments)
            if not line_segments:
                y_text += line_height
                continue
            if len(line_segments) == 1 and line_segments[0]["text"] == '---':
                draw.line([(CONTENT_X, y_text + line_height // 2), (CANVAS_WIDTH - CONTENT_RIGHT, y_text + line_height // 2)], fill=(230, 230, 230), width=2)
                y_text += line_height
                continue
            current_x = CONTENT_X
            for segment in line_segments:
                segment_font = _font_for_chunk(segment, font, large_font)
                _draw_text(
                    pilmoji,
                    (current_x, y_text),
                    segment["text"],
                    font=segment_font,
                    fill=segment["color"],
                    bold=segment.get("bold", False),
                )
                current_x += segment_font.getlength(segment["text"])
            y_text += line_height

    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG', quality=95)
    return img_byte_arr.getvalue()


async def html_to_image(markdown_text: str, render_mode: str = "full") -> bytes:
    """将 Markdown 文本渲染为图片（支持 KaTeX 公式 + 代码高亮）"""
    markdown_text = normalize_math_delimiters(markdown_text)
    env = _get_template_env()
    template = env.get_template(TEMPLATE_FILE)
    html_content = template.render(
        text=markdown_text,
        header_image_data_uri=_header_image_data_uri(),
        render_mode=render_mode,
    )

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
