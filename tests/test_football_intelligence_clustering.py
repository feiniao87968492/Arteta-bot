from plugins.arteta_football_intelligence.clustering import (
    build_story_cluster_id,
    choose_transfer_status,
)


def test_story_cluster_id_is_stable_for_same_event_subject_and_month():
    first = build_story_cluster_id("transfer", ["Arsenal"], ["Bukayo Saka"], "Premier League", 1779539400)
    second = build_story_cluster_id("transfer", ["Arsenal"], ["Bukayo Saka"], "Premier League", 1779540000)
    other_player = build_story_cluster_id("transfer", ["Arsenal"], ["Declan Rice"], "Premier League", 1779540000)

    assert first == second
    assert first != other_player


def test_transfer_status_does_not_downgrade_confirmed_with_low_source_rumor():
    assert choose_transfer_status("confirmed", "rumor", current_source_level="official", new_source_level="aggregator") == "confirmed"
    assert choose_transfer_status("negotiating", "collapsed", current_source_level="trusted_reporter", new_source_level="authoritative_media") == "collapsed"
    assert choose_transfer_status("reported", "denied", current_source_level="aggregator", new_source_level="official") == "denied"
