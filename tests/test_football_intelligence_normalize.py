from plugins.arteta_football_intelligence.normalize import (
    normalize_published_time,
    normalize_url,
)


def test_normalize_url_strips_tracking_and_fragment_but_keeps_content_query():
    url = "HTTPS://Example.COM/news/arsenal/?id=42&utm_source=x&fbclid=abc#comments"

    assert normalize_url(url) == "https://example.com/news/arsenal?id=42"


def test_normalize_url_rejects_non_http_urls():
    assert normalize_url("javascript:alert(1)") == ""
    assert normalize_url("ftp://example.com/file") == ""


def test_normalize_published_time_uses_iso_time_and_rejects_far_future():
    fetched_at = 1780000000

    value, reasons = normalize_published_time("2026-05-23T12:30:00Z", fetched_at=fetched_at)
    assert value == 1779539400
    assert reasons == []

    value, reasons = normalize_published_time("2099-01-01T00:00:00Z", fetched_at=fetched_at)
    assert value == 0
    assert "published_time_in_future" in reasons


def test_normalize_published_time_falls_back_to_fetched_at_with_reason():
    value, reasons = normalize_published_time("", fetched_at=1780000000)

    assert value == 1780000000
    assert "published_time_inferred" in reasons
