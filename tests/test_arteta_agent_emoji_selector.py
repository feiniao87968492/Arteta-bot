from plugins.arteta_agent.emoji.history import record_emoji_send, reset_emoji_history_for_tests
from plugins.arteta_agent.emoji.models import EmojiAsset, EmojiReactionDecision
from plugins.arteta_agent.emoji.selector import rank_emoji_candidates, select_emoji_asset


def asset(
    name,
    reactions,
    intensities=None,
    stances=None,
    topics=None,
    avoid_contexts=None,
    weight=1.0,
    reviewed=True,
):
    return EmojiAsset(
        name=name,
        path="/safe/{0}.png".format(name),
        relative_path="{0}.png".format(name),
        reactions=reactions,
        intensities=intensities or ["medium"],
        stances=stances or ["shared_with_user"],
        topics=topics or ["general"],
        avoid_contexts=avoid_contexts or [],
        weight=weight,
        reviewed=reviewed,
    )


def decision(reaction, intensity="medium", stance="shared_with_user", topic="general", reason_codes=None):
    return EmojiReactionDecision(
        reaction=reaction,
        intensity=intensity,
        stance=stance,
        topic=topic,
        confidence=0.9,
        reason_codes=reason_codes or [],
    )


def test_selector_prefers_exact_reaction_match():
    assets = [
        asset("approval", ["approval"], weight=5.0),
        asset("skeptical", ["skeptical"], stances=["toward_claim"], topics=["football_news"]),
    ]

    selected = select_emoji_asset(
        assets,
        decision("skeptical", stance="toward_claim", topic="football_news"),
        group_id="g1",
        request_id="r1",
    )

    assert selected.name == "skeptical"


def test_selector_vetoes_avoid_contexts():
    assets = [
        asset("tease_injury", ["teasing"], topics=["injury"], avoid_contexts=["serious_injury"], weight=99.0),
        asset("sad_injury", ["sad"], topics=["injury"]),
    ]

    ranked = rank_emoji_candidates(
        assets,
        decision("sad", topic="injury", reason_codes=["serious_injury"]),
        group_id="g1",
    )
    selected = select_emoji_asset(
        assets,
        decision("sad", topic="injury", reason_codes=["serious_injury"]),
        group_id="g1",
        request_id="r1",
    )

    assert all(item.asset.name != "tease_injury" for item in ranked)
    assert selected.name == "sad_injury"


def test_selector_excludes_recent_automatic_asset_reuse():
    reset_emoji_history_for_tests()
    record_emoji_send("g1", "first", "celebration", automatic=True, timestamp=1.0)
    assets = [
        asset("first", ["celebration"]),
        asset("second", ["celebration"]),
    ]

    selected = select_emoji_asset(assets, decision("celebration"), group_id="g1", request_id="r1")

    assert selected.name == "second"


def test_selector_returns_none_without_matching_candidate():
    selected = select_emoji_asset(
        [asset("thinking", ["thinking"])],
        decision("sad", topic="injury"),
        group_id="g1",
        request_id="r1",
    )

    assert selected is None


def test_selector_is_stable_for_fixed_seed_and_only_uses_top_three():
    assets = [
        asset("top1", ["approval"], weight=1.0),
        asset("top2", ["approval"], weight=1.0),
        asset("top3", ["approval"], weight=1.0),
        asset("outside_top3", ["approval"], weight=9999.0, reviewed=False),
    ]
    selected_names = [
        select_emoji_asset(assets, decision("approval"), group_id="g1", request_id="same").name
        for _ in range(5)
    ]
    top_three = [item.asset.name for item in rank_emoji_candidates(assets, decision("approval"), group_id="g1")[:3]]

    assert len(set(selected_names)) == 1
    assert selected_names[0] in top_three
    assert selected_names[0] != "outside_top3"


def test_selector_applies_legacy_mood_compatibility_mapping():
    assets = [
        asset("approval", ["approval"]),
        asset("frustrated", ["frustrated"]),
    ]

    positive = select_emoji_asset(
        assets,
        decision("none"),
        group_id="g1",
        request_id="r1",
        legacy_mood="positive_neutral",
    )
    negative = select_emoji_asset(
        assets,
        decision("none"),
        group_id="g1",
        request_id="r2",
        legacy_mood="negative",
    )

    assert positive.name == "approval"
    assert negative.name == "frustrated"
