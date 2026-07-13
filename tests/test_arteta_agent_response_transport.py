from plugins.arteta_agent.response.transport import choose_reply_transport


def test_reply_transport_prefers_text_for_short_plain_reply():
    decision = choose_reply_transport("早，今天先把节奏稳住。")

    assert decision.mode == "text"
    assert decision.reason == "short_plain_text"


def test_reply_transport_uses_image_for_code_formula_and_tables():
    samples = [
        "```python\nprint('hi')\n```",
        "设 $x^2 - 1 = 0$，解得 x=1 或 -1。",
        "| 球员 | 状态 |\n| --- | --- |\n| 萨卡 | 待确认 |",
    ]

    for sample in samples:
        decision = choose_reply_transport(sample)
        assert decision.mode == "image"


def test_reply_transport_does_not_render_for_favorability_notice_only():
    decision = choose_reply_transport("回答正文。\n\n【信任度上升2点】")

    assert decision.mode == "text"


def test_reply_transport_uses_image_for_long_structured_analysis():
    text = "\n".join([
        "**结论**",
        "阿森纳这套右路结构要看三层关系。",
        "",
        "**为什么**",
    ] + ["- 这一段需要展开空间、站位和职责。" for _ in range(28)])

    decision = choose_reply_transport(text)

    assert decision.mode == "image"
    assert decision.reason == "long_structured_content"


def test_reply_transport_uses_image_for_short_rich_style_tags():
    decision = choose_reply_transport("[color=#22bb22][bold][scale=1]hello[/scale][/bold][/color]")

    assert decision.mode == "image"
    assert decision.reason == "rich_style"
