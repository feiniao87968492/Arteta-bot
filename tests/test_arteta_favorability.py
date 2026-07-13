from plugins.arteta_agent.response.favorability import (
    evaluate_favorability,
    format_favorability_notice,
    strip_legacy_favor_markers,
)


def test_strip_legacy_favor_marker_removes_marker_without_scoring():
    clean, marker = strip_legacy_favor_markers("很好。\n【好感度+】")

    assert clean == "很好。"
    assert marker == "【好感度+】"


def test_favorability_plain_chat_defaults_to_zero():
    decision = evaluate_favorability("你好", "在，训练开始。")

    assert decision.delta == 0
    assert decision.reason == ""


def test_favorability_quality_contribution_gets_small_deterministic_delta():
    decision = evaluate_favorability(
        "我帮大家整理了赛程和来源，塔子看看",
        "这个有用，来源也清楚。",
    )

    assert 1 <= decision.delta <= 3
    assert "贡献" in decision.reason


def test_favorability_abuse_gets_small_deterministic_penalty():
    decision = evaluate_favorability("你这个废物教练下课吧", "保持尊重。")

    assert -8 <= decision.delta <= -1
    assert decision.delta < 0
    assert "负面" in decision.reason


def test_favorability_notice_hides_zero_and_small_changes():
    assert format_favorability_notice(0, "青训生", "青训生", 0) == ""
    assert format_favorability_notice(2, "青训生", "青训生", 2) == ""


def test_favorability_notice_shows_level_change_or_large_delta_without_red_tags():
    level_notice = format_favorability_notice(2, "青训生", "一线队", 52)
    large_notice = format_favorability_notice(-5, "一线队", "一线队", 195)

    assert "定位更新" in level_notice
    assert "信任度下降5点" in large_notice
    assert "[red]" not in level_notice + large_notice


def test_arteta_chat_uses_shared_favorability_without_random_marker_ranges():
    from pathlib import Path

    source = Path("plugins/arteta_chat.py").read_text(encoding="utf-8")

    assert "evaluate_favorability" in source
    assert "format_favorability_notice" in source
    assert "strip_legacy_favor_markers" in source
    assert "FAVOR_MARKERS = {" not in source
    assert "random.randint(min(min_val" not in source
    assert "【信任度无变化】" not in source
