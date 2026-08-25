"""HTTP bridge for reading X/Twitter status pages with a persistent browser profile.

Run this separately from the bot:

    python -m uvicorn tools.x_fetch_bridge:app --host 127.0.0.1 --port 8801

The first login is done by running the same module with ``--login`` in a
terminal session that can show the browser. The bot only calls the HTTP API.
"""

import argparse
import asyncio
import os
import re
from typing import Any, Dict
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel


def _load_env_file(path: str) -> None:
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env_file(os.environ.get("ARTETA_ENV_FILE", ".env.prod"))

BRIDGE_API_KEY = (
    os.environ.get("ARTETA_X_FETCH_BRIDGE_KEY", "").strip()
    or os.environ.get("ARTETA_X_FETCH_API_KEY", "").strip()
)
PROFILE_DIR = os.environ.get("ARTETA_X_FETCH_PROFILE_DIR", "/opt/arteta_bot/data/x_browser_profile").strip()
HEADLESS = os.environ.get("ARTETA_X_FETCH_HEADLESS", "1").strip().lower() not in {"0", "false", "no"}
NAV_TIMEOUT_MS = int(os.environ.get("ARTETA_X_FETCH_NAV_TIMEOUT_MS", "45000") or "45000")


class XFetchRequest(BaseModel):
    url: str


def _check_auth(authorization: str) -> None:
    if not BRIDGE_API_KEY:
        return
    expected = "Bearer " + BRIDGE_API_KEY
    if authorization != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


def _tweet_id_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if domain not in {"x.com", "twitter.com", "mobile.twitter.com"}:
        return ""
    if parsed.scheme not in {"http", "https"}:
        return ""
    match = re.search(r"/status(?:es)?/(\d+)", parsed.path)
    return match.group(1) if match else ""


def _normalize_tweet_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    text = str(payload.get("text") or "").strip()
    if not text:
        return {}
    return {
        "tweet_id": str(payload.get("tweet_id") or ""),
        "url": str(payload.get("url") or ""),
        "author_name": str(payload.get("author_name") or ""),
        "author_username": str(payload.get("author_username") or ""),
        "created_at": str(payload.get("created_at") or ""),
        "text": text,
    }


async def _extract_with_playwright(url: str) -> Dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise HTTPException(status_code=503, detail="playwright is not available: {0}".format(exc))

    os.makedirs(PROFILE_DIR, exist_ok=True)
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=HEADLESS,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = await context.new_page()
        try:
            page.set_default_timeout(NAV_TIMEOUT_MS)
            await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            try:
                await page.wait_for_selector("article", timeout=15000)
            except Exception:
                pass
            payload = await page.evaluate(
                """() => {
                    const article = document.querySelector('article');
                    if (!article) return {};
                    const textParts = Array.from(article.querySelectorAll('[data-testid="tweetText"]'))
                        .map((node) => node.innerText || node.textContent || '')
                        .filter(Boolean);
                    const text = textParts.join('\\n').trim();
                    const userNameNode = article.querySelector('[data-testid="User-Name"]');
                    const userNameText = userNameNode ? (userNameNode.innerText || userNameNode.textContent || '') : '';
                    const timeNode = article.querySelector('time');
                    const linkNode = timeNode ? timeNode.closest('a') : null;
                    const match = (location.pathname || '').match(/status(?:es)?\\/(\\d+)/);
                    const handleMatch = userNameText.match(/@([A-Za-z0-9_]{1,20})/);
                    const name = (userNameText.split('\\n')[0] || '').trim();
                    return {
                        tweet_id: match ? match[1] : '',
                        url: linkNode ? linkNode.href : location.href,
                        author_name: name,
                        author_username: handleMatch ? handleMatch[1] : '',
                        created_at: timeNode ? (timeNode.getAttribute('datetime') || '') : '',
                        text,
                    };
                }"""
            )
            normalized = _normalize_tweet_payload(payload)
            if normalized:
                return normalized
            raise HTTPException(status_code=404, detail="tweet text not found; login may be required")
        finally:
            await page.close()
            await context.close()


async def fetch_status_text(url: str) -> Dict[str, Any]:
    tweet_id = _tweet_id_from_url(url)
    if not tweet_id:
        raise HTTPException(status_code=400, detail="only x.com/twitter.com status URLs are supported")
    try:
        result = await _extract_with_playwright(url)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="browser extraction failed: {0}: {1}".format(exc.__class__.__name__, exc))
    result["tweet_id"] = result.get("tweet_id") or tweet_id
    result["backend"] = "playwright-profile"
    return result


app = FastAPI(title="Arteta X Fetch Bridge")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "healthy"}


@app.post("/fetch")
async def fetch(request: XFetchRequest, authorization: str = Header("")) -> Dict[str, Any]:
    _check_auth(authorization)
    return await fetch_status_text(request.url)


async def _login() -> None:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise SystemExit("playwright is not available: {0}".format(exc))
    os.makedirs(PROFILE_DIR, exist_ok=True)
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = await context.new_page()
        await page.goto("https://x.com/home", wait_until="domcontentloaded")
        print("Log in to X in the opened browser, then press Enter here to save the profile.")
        await asyncio.get_event_loop().run_in_executor(None, input)
        await context.close()


async def _wait_for_login_signal(path: str, timeout_seconds: int = 900) -> None:
    if not path:
        await asyncio.get_event_loop().run_in_executor(None, input)
        return
    deadline = asyncio.get_event_loop().time() + max(1, int(timeout_seconds or 900))
    while asyncio.get_event_loop().time() < deadline:
        if os.path.exists(path):
            return
        await asyncio.sleep(1)
    raise TimeoutError("login signal file not found: {0}".format(path))


async def _login_until_signal(signal_file: str, timeout_seconds: int = 900) -> None:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise SystemExit("playwright is not available: {0}".format(exc))
    os.makedirs(PROFILE_DIR, exist_ok=True)
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = await context.new_page()
        await page.goto("https://x.com/home", wait_until="domcontentloaded")
        print("Log in to X in the opened browser, then create this signal file: {0}".format(signal_file))
        await _wait_for_login_signal(signal_file, timeout_seconds=timeout_seconds)
        await context.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", action="store_true", help="open a visible browser to create/update the X login profile")
    parser.add_argument("--signal-file", default="", help="file whose existence ends login mode and saves the profile")
    parser.add_argument("--login-timeout", type=int, default=900, help="seconds to wait for --signal-file")
    args = parser.parse_args()
    if args.login:
        if args.signal_file:
            asyncio.run(_login_until_signal(args.signal_file, timeout_seconds=args.login_timeout))
        else:
            asyncio.run(_login())


if __name__ == "__main__":
    main()
