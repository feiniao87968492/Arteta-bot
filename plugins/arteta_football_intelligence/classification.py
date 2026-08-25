from dataclasses import dataclass


@dataclass
class EventClassification:
    event_type: str
    status: str = "reported"
    confidence: float = 0.6


def classify_event(title: str, summary: str = "") -> EventClassification:
    text = ("%s %s" % (title or "", summary or "")).lower()
    if _has_any(text, ("deny", "denied", "no agreement", "not true")) and _has_any(text, ("transfer", "signing", "deal")):
        return EventClassification("transfer", "denied", 0.78)
    if _has_any(text, ("transfer", "signing", "signs", "joins", "linked", "talks", "bid", "agreement")):
        return EventClassification("transfer", _transfer_status(text), 0.72)
    if _has_any(text, ("injury", "injured", "ruled out", "knock", "hamstring")):
        return EventClassification("injury", "reported", 0.72)
    if _has_any(text, ("return to training", "returns to training", "back in training", "training update")):
        return EventClassification("training", "reported", 0.7)
    if _has_any(text, ("full-time", "full time", "beat ", " draw", "result", "lost to", "defeated")):
        return EventClassification("match_result", "confirmed", 0.68)
    if _has_any(text, ("starting xi", "lineup", "line-up", "team news")):
        return EventClassification("lineup", "confirmed", 0.68)
    if _has_any(text, ("press conference", "said after the match", "pre-match press")):
        return EventClassification("press_conference", "reported", 0.68)
    if _has_any(text, ("suspension", "suspended", "ban upheld")):
        return EventClassification("suspension", "reported", 0.68)
    if _has_any(text, ("contract", "extends deal", "new deal")):
        return EventClassification("contract", "reported", 0.68)
    if _has_any(text, ("club announcement", "official statement", "academy role")):
        return EventClassification("club_announcement", "reported", 0.62)
    return EventClassification("other", "reported", 0.4)


def _has_any(text: str, markers) -> bool:
    return any(marker in text for marker in markers)


def _transfer_status(text: str) -> str:
    if _has_any(text, ("officially confirm", "officially announce", "complete transfer", "completed transfer", "signs", "joins")):
        return "confirmed"
    if _has_any(text, ("agreement reached", "agreed deal")):
        return "agreement_reached"
    if _has_any(text, ("advanced", "final stages")):
        return "advanced"
    if _has_any(text, ("talks", "negotiating", "negotiations")):
        return "negotiating"
    if _has_any(text, ("bid", "offer submitted")):
        return "bid_submitted"
    if _has_any(text, ("linked", "rumor", "rumour")):
        return "rumor"
    return "reported"
