from plugins.arteta_agent.emoji.gate import decide_emoji_gate
from plugins.arteta_agent.emoji.history import reset_emoji_history_for_tests, record_emoji_send
from plugins.arteta_agent.emoji.models import EmojiGateContext
from plugins.arteta_agent.response.style import ResponseStyleProfile


def make_context(
    user_text,
    assistant_text="在。",
    profile=None,
    trace=None,
    emoji_enabled=True,
    tool_disabled=False,
    has_assets=True,
    group_id="group-1",
):
    return EmojiGateContext(
        user_text=user_text,
        assistant_text=assistant_text,
        group_id=group_id,
        profile=profile or ResponseStyleProfile("casual", "light", "expanded"),
        trace=trace,
        emoji_enabled=emoji_enabled,
        tool_disabled=tool_disabled,
        has_assets=has_assets,
    )


def test_gate_skips_plain_neutral_reply():
    decision = decide_emoji_gate(make_context("塔子在吗", "在。"))

    assert decision.should_send is False
    assert "low_signal" in decision.reason_codes


def test_gate_allows_explicit_emoji_request_even_when_style_disallows_auto():
    profile = ResponseStyleProfile("current_news", "medium", "medium", allow_mood_emoji=False)

    decision = decide_emoji_gate(make_context(
        "发个表情",
        "可以。",
        profile=profile,
        emoji_enabled=True,
    ))

    assert decision.should_send is True
    assert decision.explicit_request is True
    assert "explicit_request" in decision.reason_codes


def test_gate_respects_user_explicit_emoji_ban():
    decision = decide_emoji_gate(make_context("不要发表情", "收到。"))

    assert decision.should_send is False
    assert "user_disabled_emoji" in decision.reason_codes


def test_gate_skips_technical_permission_trace_and_news_turns():
    cases = [
        make_context("这道数学题怎么解", "先设 x。"),
        make_context("需要权限吗", "[PermissionRequired] 需要管理员确认。"),
        make_context("看一下 trace", "工具调用如下。", trace={"tools": [{"name": "show_agent_trace"}]}),
        make_context("核实一下最新转会消息", "需要来源。"),
    ]

    for context in cases:
        decision = decide_emoji_gate(context)
        assert decision.should_send is False
        assert decision.reason_codes


def test_gate_blocks_when_policy_or_tool_disabled():
    disabled_auto = decide_emoji_gate(make_context(
        "萨卡绝杀了！",
        "这球太关键了。",
        profile=ResponseStyleProfile("casual", "light", "expanded", allow_mood_emoji=True),
        emoji_enabled=False,
    ))
    disabled_tool_auto = decide_emoji_gate(make_context(
        "萨卡绝杀了！",
        "这球太关键了。",
        profile=ResponseStyleProfile("casual", "light", "expanded", allow_mood_emoji=True),
        tool_disabled=True,
    ))
    explicit_policy_disabled = decide_emoji_gate(make_context(
        "发个表情",
        "可以。",
        emoji_enabled=False,
    ))
    explicit_tool_disabled = decide_emoji_gate(make_context(
        "发个表情",
        "可以。",
        tool_disabled=True,
    ))

    assert disabled_auto.should_send is False
    assert "emoji_policy_disabled" in disabled_auto.reason_codes
    assert disabled_tool_auto.should_send is False
    assert "emoji_tool_disabled" in disabled_tool_auto.reason_codes
    assert explicit_policy_disabled.should_send is False
    assert "emoji_policy_disabled" in explicit_policy_disabled.reason_codes
    assert explicit_tool_disabled.should_send is False
    assert "emoji_tool_disabled" in explicit_tool_disabled.reason_codes


def test_gate_blocks_when_no_assets_or_previous_tool_call_exists():
    no_assets = decide_emoji_gate(make_context("发个表情", "可以。", has_assets=False))
    existing_call = decide_emoji_gate(make_context(
        "萨卡绝杀了！",
        "发过了。",
        profile=ResponseStyleProfile("casual", "light", "expanded", allow_mood_emoji=True),
        trace={"tools": [{"name": "send_mood_emoji"}]},
    ))

    assert no_assets.should_send is False
    assert "no_assets" in no_assets.reason_codes
    assert existing_call.should_send is False
    assert "emoji_already_called" in existing_call.reason_codes


def test_gate_auto_cooldown_does_not_block_explicit_request():
    reset_emoji_history_for_tests()
    for index in range(2):
        record_emoji_send("cooldown-group", "asset-{0}".format(index), "celebration", automatic=True, timestamp=float(index))

    auto_decision = decide_emoji_gate(make_context(
        "萨卡绝杀了！",
        "太关键了。",
        profile=ResponseStyleProfile("casual", "light", "expanded", allow_mood_emoji=True),
        group_id="cooldown-group",
    ))
    explicit_decision = decide_emoji_gate(make_context(
        "发个表情",
        "可以。",
        group_id="cooldown-group",
    ))

    assert auto_decision.should_send is False
    assert "auto_cooldown" in auto_decision.reason_codes
    assert explicit_decision.should_send is True
    assert explicit_decision.explicit_request is True
