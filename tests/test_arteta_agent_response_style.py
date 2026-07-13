from plugins.arteta_agent.response.style import (
    build_response_style_guard,
    detect_response_style_profile,
)


def test_response_style_profile_classifies_core_modes():
    casual = detect_response_style_profile("早")
    assert casual.mode == "casual"
    assert casual.persona_intensity == "light"
    assert casual.target_length == "short"
    assert casual.allow_mood_emoji is False
    assert casual.prefer_image_render is False

    meme = detect_response_style_profile("这图笑死，怎么看", has_image=True)
    assert meme.mode == "meme"
    assert meme.persona_intensity == "light"
    assert meme.target_length == "short"
    assert meme.allow_mood_emoji is True

    opinion = detect_response_style_profile("罗杰斯适合阿森纳吗")
    assert opinion.mode == "football_opinion"
    assert opinion.persona_intensity == "medium"
    assert opinion.target_length == "medium"

    news = detect_response_style_profile("萨卡最新伤情怎么样")
    assert news.mode == "current_news"
    assert news.persona_intensity == "medium"
    assert news.target_length == "medium"
    assert news.allow_mood_emoji is False

    tactics = detect_response_style_profile("详细解释阿森纳右路进攻结构")
    assert tactics.mode == "tactical_deep_dive"
    assert tactics.persona_intensity == "strong"
    assert tactics.target_length == "long"
    assert tactics.prefer_image_render is True

    serious = detect_response_style_profile("你刚才用了什么工具")
    assert serious.mode == "serious"
    assert serious.persona_intensity == "light"
    assert serious.target_length == "medium"


def test_response_style_profile_uses_context_over_broad_keywords():
    news = detect_response_style_profile(
        "这段 PDF 里说阿森纳财政健康，帮我总结并核一下来源",
        has_document=True,
        current_information_required=True,
    )
    assert news.mode == "current_news"
    assert "current_information_required" in news.reason_codes

    meme = detect_response_style_profile(
        "记住以后短一点，然后评价下这张图",
        has_image=True,
        route_hint="memory_image",
    )
    assert meme.mode == "meme"
    assert meme.target_length == "short"


def test_build_response_style_guard_is_short_and_mode_specific():
    profile = detect_response_style_profile("这图笑死，怎么看", has_image=True)

    guard = build_response_style_guard(profile)

    assert "【本轮表达模式：梗图轻互动】" in guard
    assert "120 字以内" in guard
    assert "不要描述自己的肢体动作" in guard
    assert "不要强行上升到战术哲学" in guard
    assert "不要只模仿最近群聊上下文里的旧短回复" in guard
    assert len([line for line in guard.splitlines() if line.strip()]) <= 8


def test_arteta_chat_appends_style_module_guard_for_current_turn():
    from plugins import arteta_chat

    messages = [{"role": "system", "content": "BASE"}]

    arteta_chat.append_current_turn_style_guard(
        messages,
        user_message="这图笑死，怎么看",
        has_image=True,
    )

    assert messages[-1]["role"] == "user"
    assert "APP_GENERATED_RESPONSE_STYLE" in messages[-1]["content"]
    assert "【本轮表达模式：梗图轻互动】" in messages[-1]["content"]
    assert "120 字以内" in messages[-1]["content"]
