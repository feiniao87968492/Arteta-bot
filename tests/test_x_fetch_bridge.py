import asyncio
import os

from fastapi import HTTPException

from tools import x_fetch_bridge as bridge


def test_x_bridge_loads_env_file_without_shell_parsing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env.prod"
    env_file.write_text(
        "COMMAND_START=['', '/']\n"
        "ARTETA_X_FETCH_API_KEY=x-secret\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ARTETA_X_FETCH_API_KEY", raising=False)

    bridge._load_env_file(str(env_file))

    assert os.environ["ARTETA_X_FETCH_API_KEY"] == "x-secret"


def test_x_bridge_auth_rejects_wrong_bearer(monkeypatch):
    monkeypatch.setattr(bridge, "BRIDGE_API_KEY", "x-secret")

    try:
        bridge._check_auth("Bearer wrong")
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("expected HTTPException")


def test_x_bridge_accepts_only_status_urls():
    assert bridge._tweet_id_from_url("https://x.com/David_Ornstein/status/2074251813545742720") == "2074251813545742720"
    assert bridge._tweet_id_from_url("https://twitter.com/Arsenal/statuses/123") == "123"
    assert bridge._tweet_id_from_url("https://example.com/status/123") == ""
    assert bridge._tweet_id_from_url("file:///etc/passwd") == ""


def test_x_bridge_extracts_tweet_from_dom_result():
    payload = {
        "tweet_id": "123",
        "url": "https://x.com/u/status/123",
        "author_name": "David Ornstein",
        "author_username": "David_Ornstein",
        "created_at": "2026-07-07T10:00:00.000Z",
        "text": "Original post text.",
    }

    result = bridge._normalize_tweet_payload(payload)

    assert result == payload


def test_x_bridge_rejects_empty_tweet_text():
    result = bridge._normalize_tweet_payload({"tweet_id": "123", "text": ""})

    assert result == {}


def test_x_bridge_fetch_uses_playwright_extractor(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "PROFILE_DIR", str(tmp_path / "profile"))

    async def fake_extract(url):
        return {
            "tweet_id": "2074251813545742720",
            "url": url,
            "author_name": "David Ornstein",
            "author_username": "David_Ornstein",
            "created_at": "",
            "text": "Original X text from browser.",
        }

    monkeypatch.setattr(bridge, "_extract_with_playwright", fake_extract)

    result = asyncio.run(bridge.fetch_status_text(
        "https://x.com/David_Ornstein/status/2074251813545742720"
    ))

    assert result["text"] == "Original X text from browser."
    assert result["backend"] == "playwright-profile"


def test_x_bridge_converts_playwright_failure_to_http_exception(monkeypatch):
    async def broken_extract(url):
        raise RuntimeError("browser timed out")

    monkeypatch.setattr(bridge, "_extract_with_playwright", broken_extract)

    try:
        asyncio.run(bridge.fetch_status_text("https://x.com/user/status/123"))
    except HTTPException as exc:
        assert exc.status_code == 503
        assert "browser timed out" in str(exc.detail)
    else:
        raise AssertionError("expected HTTPException")


def test_x_bridge_wait_for_login_signal_returns_when_file_exists(tmp_path):
    wait_file = tmp_path / "done"
    wait_file.write_text("done", encoding="utf-8")

    asyncio.run(bridge._wait_for_login_signal(str(wait_file), timeout_seconds=1))
