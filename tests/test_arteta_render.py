import io
import asyncio

from PIL import Image

from plugins.arteta_agent.context import ToolContext
from plugins.arteta_agent.tools import render as agent_render
from plugins.arteta_render import (
    HEADER_IMAGE_PATH,
    _get_template_env,
    _header_image_data_uri,
    normalize_inline_style_markup,
    parse_inline_style_chunks,
    style_tags_to_html,
    text_to_tactical_board,
)


def test_parse_inline_style_chunks_supports_rich_trace_style():
    chunks = parse_inline_style_chunks("[red][bold][large]【Agent 调度】[/large][/bold][/red]")

    assert chunks == [{
        "text": "【Agent 调度】",
        "color": (220, 38, 38),
        "bold": True,
        "large": True,
        "scale": 1.2,
    }]


def test_parse_inline_style_chunks_supports_custom_scale_and_color():
    chunks = parse_inline_style_chunks("[color=#16a34a][scale=5]大字[/scale][/color]")

    assert chunks == [{
        "text": "大字",
        "color": (22, 163, 74),
        "bold": False,
        "large": False,
        "scale": 5.0,
    }]


def test_normalize_inline_style_markup_converts_html_span_to_style_tags():
    text = '外号 <span style="color:red;font-size:24px;font-weight:bold;">飞鸟</span>'

    normalized = normalize_inline_style_markup(text)

    assert normalized == "外号 [red][bold][large]飞鸟[/large][/bold][/red]"
    assert "<span" not in normalized


def test_style_tags_to_html_sanitizes_raw_style_span():
    text = '外号 <span style="color:red;font-size:24px;font-weight:bold;">飞鸟</span>'

    html = style_tags_to_html(text)

    assert 'style="' not in html
    assert '<span class="arsenal-red"><span class="arsenal-bold"><span class="arsenal-large">飞鸟</span></span></span>' in html


def test_style_tags_to_html_supports_custom_scale_and_color():
    html = style_tags_to_html("[color=#16a34a][scale=5]大字[/scale][/color]")

    assert 'style="color: #16a34a"' in html
    assert 'style="font-size: 5em"' in html


def test_agent_render_markdown_converts_style_tags_before_html(monkeypatch, tmp_path):
    captured = {}

    async def fake_html_to_image(markdown):
        captured["markdown"] = markdown
        return b"\x89PNG\r\n\x1a\n"

    def fake_write_artifact(prefix, content):
        return str(tmp_path / (prefix + ".png"))

    monkeypatch.setattr(agent_render._get_arteta_render(), "html_to_image", fake_html_to_image)
    monkeypatch.setattr(agent_render, "_write_artifact", fake_write_artifact)

    ctx = ToolContext(bot=None, event=None, user_id="u", group_id="g")
    result = asyncio.run(agent_render.render_markdown_to_image(
        ctx,
        "[red]red[/red]\n[color=green]green[/color]",
    ))

    assert result.startswith("[RenderedImage:")
    assert '<span class="arsenal-red">red</span>' in captured["markdown"]
    assert 'style="color: green"' in captured["markdown"]


def test_render_template_uses_reply_header_image():
    html = _get_template_env().get_template("arteta_render.html").render(
        text="hello",
        header_image_data_uri=_header_image_data_uri(),
        render_mode="full",
    )

    assert HEADER_IMAGE_PATH.endswith("situation_room_header.png")
    assert 'class="reply-header"' in html
    assert 'class="notice-stage"' in html
    assert 'class="notice-frame"' in html
    assert 'class="notice-frame-red"' in html
    assert 'class="notice-paper"' in html
    assert 'class="notice-frame-gold"' not in html
    assert "data:image/png;base64," in html
    assert "ARSENAL | TACTICAL BOARD" not in html


def test_render_template_supports_compact_mode_without_header_or_nested_frames():
    html = _get_template_env().get_template("arteta_render.html").render(
        text="short",
        header_image_data_uri=_header_image_data_uri(),
        render_mode="compact",
    )

    assert 'class="reply-header"' not in html
    assert 'class="notice-stage compact"' in html
    assert 'class="notice-frame"' not in html
    assert 'class="notice-frame-red"' not in html
    assert 'class="notice-frame-gold"' not in html
    assert 'class="notice-paper compact"' in html


def test_text_to_tactical_board_uses_image_header_and_notice_frame():
    image_bytes = text_to_tactical_board("hello")

    image = Image.open(io.BytesIO(image_bytes))

    assert image.size[0] == 1500
    assert image.size[1] > 500
    assert image.getpixel((20, 20)) != (219, 0, 7)
    assert image.getpixel((35, 561)) == (15, 76, 129)
    assert image.getpixel((50, 579)) == (219, 0, 7)
    assert image.getpixel((64, 594)) == (215, 191, 106)


def test_text_to_tactical_board_renders_scaled_custom_color_text():
    image_bytes = text_to_tactical_board("[color=#006400][bold][scale=3]飞鸟[/scale][/bold][/color]")

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    greenish_pixels = 0
    for r, g, b in image.getdata():
        if g >= 70 and r <= 30 and b <= 30:
            greenish_pixels += 1

    assert greenish_pixels > 100
