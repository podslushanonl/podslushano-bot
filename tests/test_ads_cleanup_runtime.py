"""Focused checks for the lighter /ads UI and newsletter welcome e-mail."""
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")

from aiohttp import web  # noqa: E402

import ad_ads_cleanup_runtime as cleanup  # noqa: E402
import ad_season_campaign_runtime as season  # noqa: E402


def test_static_density_patch() -> None:
    css = (ROOT / "static" / "ads-site" / "q4-cleanup.css").read_text(encoding="utf-8")
    js = (ROOT / "static" / "ads-site" / "q4-cleanup.js").read_text(encoding="utf-8")
    assert ".hero-card," in css
    assert ".season-panel," in css
    assert ".gift-fab," in css
    assert "display: none !important" in css
    assert "font-size: 38px" in css
    assert "Как проходит размещение." in js
    assert "Забрать −26%" in js
    assert "/ads-season/welcome" in js
    assert "email_sent" in js


def test_welcome_template() -> None:
    html = cleanup._welcome_email_html(
        "https://example.test", "https://example.test/unsubscribe?token=abc"
    )
    text = cleanup._welcome_email_text(
        "https://example.test", "https://example.test/unsubscribe?token=abc"
    )
    assert "Podslushano.nl" in html
    assert "Спасибо за подписку" in html
    assert "−26%" in html
    assert "Выбрать рекламный формат" in html
    assert "unsubscribe?token=abc" in html
    assert "−26%" in text
    assert "https://example.test/ads" in text


class FakeRequest:
    scheme = "https"
    host = "ads.example.test"

    def __init__(self, data):
        self._data = data

    async def post(self):
        return self._data


async def test_signup_wrapper() -> None:
    real_original = cleanup._ORIGINAL_SUBSCRIBE
    real_sender = cleanup._send_welcome_email
    captured = {}

    async def fake_original(_request):
        return web.json_response({"ok": True, "token": "signed", "discount": 26})

    async def fake_sender(email, base_url):
        captured["email"] = email
        captured["base_url"] = base_url
        return True

    cleanup._ORIGINAL_SUBSCRIBE = fake_original
    cleanup._send_welcome_email = fake_sender
    try:
        response = await cleanup._newsletter_subscribe_with_welcome(
            FakeRequest({"email": "buyer@example.com", "consent": "1"})
        )
        payload = json.loads(response.text)
        assert payload["ok"] is True
        assert payload["email_sent"] is True
        assert captured == {
            "email": "buyer@example.com",
            "base_url": "https://ads.example.test",
        }
    finally:
        cleanup._ORIGINAL_SUBSCRIBE = real_original
        cleanup._send_welcome_email = real_sender


async def test_existing_subscriber_welcome() -> None:
    real_token_email = season._token_email
    real_campaign = season._campaign_active
    real_active = cleanup._subscriber_is_active
    real_sender = cleanup._send_welcome_email

    season._token_email = lambda token: "buyer@example.com" if token == "valid" else None
    season._campaign_active = lambda: True
    cleanup._subscriber_is_active = lambda email: asyncio.sleep(0, result=email == "buyer@example.com")
    cleanup._send_welcome_email = lambda email, base: asyncio.sleep(0, result=True)
    try:
        response = await cleanup.newsletter_welcome_existing(FakeRequest({"token": "valid"}))
        payload = json.loads(response.text)
        assert response.status == 200
        assert payload == {"ok": True, "email_sent": True}
    finally:
        season._token_email = real_token_email
        season._campaign_active = real_campaign
        cleanup._subscriber_is_active = real_active
        cleanup._send_welcome_email = real_sender


async def test_page_injection() -> None:
    real_original = cleanup._ORIGINAL_ADS_PAGE

    async def fake_page(_request):
        return web.Response(text="<html><head></head><body>ads</body></html>", content_type="text/html")

    cleanup._ORIGINAL_ADS_PAGE = fake_page
    try:
        response = await cleanup._ads_page_with_density_cleanup(SimpleNamespace())
        assert "q4-cleanup.css" in response.text
        assert "q4-cleanup.js" in response.text
    finally:
        cleanup._ORIGINAL_ADS_PAGE = real_original


def main() -> None:
    test_static_density_patch()
    test_welcome_template()
    asyncio.run(test_signup_wrapper())
    asyncio.run(test_existing_subscriber_welcome())
    asyncio.run(test_page_injection())
    print("[OK] Ads cleanup: lighter UI + branded welcome e-mail + existing subscriber recovery")


if __name__ == "__main__":
    main()
