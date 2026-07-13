from plugins.arteta_agent.emoji.classifier import classify_emoji_reaction


def test_classifier_detects_core_reaction_scenarios():
    cases = [
        ("萨卡绝杀了！", "这就是我们要的爆发。", "celebration"),
        ("领先两球又被扳平", "这种收尾确实让人红温。", "frustrated"),
        ("这消息靠谱吗？", "先别信，等可靠来源。", "skeptical"),
        ("前五句像遗书，最后突然晋级", "这反转确实有节目效果。", "amused"),
        ("球员重伤赛季报销", "这事最重要的是祝他恢复。", "sad"),
        ("突然官宣新援", "这个消息来得太突然了。", "surprised"),
        ("这题不会做，感觉要崩溃了", "别急，慢慢拆能做出来。", "encouraging"),
        ("今天真的很难受", "理解，这种时候确实不好受。", "comforting"),
    ]

    for user_text, assistant_text, expected in cases:
        decision = classify_emoji_reaction(user_text=user_text, assistant_text=assistant_text)
        assert decision.reaction == expected
        assert decision.confidence >= 0.75


def test_classifier_does_not_turn_negated_celebration_into_celebration():
    decision = classify_emoji_reaction(
        user_text="这不是庆祝，这是讽刺",
        assistant_text="确实不是庆祝，更像是在阴阳。",
    )

    assert decision.reaction != "celebration"


def test_classifier_downweights_quoted_reaction_words():
    decision = classify_emoji_reaction(
        user_text="为什么有人说“笑死”？",
        assistant_text="这是别人表达强烈反应的说法。",
    )

    assert decision.reaction != "amused"
    assert decision.confidence < 0.75


def test_classifier_uses_assistant_stance_over_user_quote():
    decision = classify_emoji_reaction(
        user_text="有人说“笑死”，但其实是球员重伤赛季报销",
        assistant_text="这不适合开玩笑，重伤只该祝他恢复。",
    )

    assert decision.reaction == "sad"
    assert decision.reaction != "amused"
    assert "assistant_stance" in decision.reason_codes


def test_classifier_returns_none_for_low_confidence_text():
    decision = classify_emoji_reaction(
        user_text="塔子在吗",
        assistant_text="在。",
    )

    assert decision.reaction == "none"
    assert decision.confidence < 0.60
