DEFAULT_MAX_AGE_SECONDS = {
    "live_score": 90,
    "match_result": 30 * 60,
    "lineup": 10 * 60,
    "injury": 6 * 3600,
    "transfer": 3 * 3600,
    "contract": 6 * 3600,
    "fixture": 12 * 3600,
    "standings": 3 * 3600,
    "training": 8 * 3600,
    "press_conference": 12 * 3600,
    "player_form": 24 * 3600,
    "club_announcement": 3650 * 86400,
    "other": 12 * 3600,
}


def max_age_for_event_type(event_type: str) -> int:
    return int(DEFAULT_MAX_AGE_SECONDS.get(str(event_type or "other"), DEFAULT_MAX_AGE_SECONDS["other"]))
