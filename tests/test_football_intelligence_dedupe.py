from plugins.arteta_football_intelligence.dedupe import (
    build_event_key,
    canonical_content_fingerprint,
    is_duplicate_candidate,
)


def test_content_fingerprint_normalizes_title_source_and_url():
    first = canonical_content_fingerprint(" Arsenal   sign striker!! ", "BBC", "https://example.com/a?utm_source=x")
    second = canonical_content_fingerprint("Arsenal sign striker", "BBC", "https://example.com/a")

    assert first == second


def test_event_key_keeps_different_players_and_matches_separate():
    saka_key = build_event_key("injury", teams=["Arsenal"], players=["Bukayo Saka"], competition="Premier League", published_at=1779539400)
    rice_key = build_event_key("injury", teams=["Arsenal"], players=["Declan Rice"], competition="Premier League", published_at=1779539400)
    match_key = build_event_key("match_result", teams=["Arsenal", "Chelsea"], players=[], competition="Premier League", published_at=1779539400)

    assert saka_key != rice_key
    assert saka_key.startswith("injury|")
    assert match_key == "match_result|arsenal-chelsea|premier league|2026-05-23"


def test_duplicate_candidate_checks_url_title_and_event_key():
    existing = {
        "canonical_url": "https://example.com/a",
        "content_hash": "hash-a",
        "event_key": "transfer|player|arsenal|2026-05",
    }

    assert is_duplicate_candidate(existing, {"canonical_url": "https://example.com/a"}) is True
    assert is_duplicate_candidate(existing, {"content_hash": "hash-a"}) is True
    assert is_duplicate_candidate(existing, {"event_key": "transfer|player|arsenal|2026-05"}) is True
    assert is_duplicate_candidate(existing, {"event_key": "injury|player|arsenal|2026-05"}) is False
