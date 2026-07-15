from plugins.arteta_football_intelligence.classification import classify_event


def test_classifies_core_event_types_with_rule_only_logic():
    assert classify_event("Arsenal complete transfer signing", "").event_type == "transfer"
    assert classify_event("Arsenal transfer rumor grows", "").event_type == "transfer"
    assert classify_event("Saka injury update after training", "").event_type == "injury"
    assert classify_event("Odegaard returns to training", "").event_type == "training"
    assert classify_event("Full-time: Arsenal beat Chelsea 2-1", "").event_type == "match_result"
    assert classify_event("Arsenal starting XI and lineup confirmed", "").event_type == "lineup"
    assert classify_event("Arteta press conference after the match", "").event_type == "press_conference"
    assert classify_event("Club announcement: new academy role", "").event_type == "club_announcement"


def test_transfer_status_uses_rule_source_without_claiming_official_confirmation():
    official = classify_event("Arsenal officially confirm new signing", "")
    rumor = classify_event("Arsenal linked with striker as talks continue", "")
    denied = classify_event("Club deny transfer agreement", "")

    assert official.event_type == "transfer"
    assert official.status == "confirmed"
    assert rumor.status in {"rumor", "reported", "negotiating"}
    assert denied.status == "denied"


def test_uncertain_content_defaults_to_other_reported():
    result = classify_event("Arsenal launch community mural", "Supporters gathered in north London.")

    assert result.event_type == "other"
    assert result.status == "reported"
