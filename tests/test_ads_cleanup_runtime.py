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
    assert ".gift-intro" in css
    assert ".gift-fab.unlocked" in css
    assert "activeGiftGlow" in css
    assert "font-size: 38px" in css
    assert "Как проходит размещение." in js
    assert "У вас подарок" in js
    assert "giftIntro" in js
    assert "Забрать −26%" in js
    assert "/ads-season/welcome" in js
    assert "email_sent" in js


def test_welcome_template() -> None:
    html_body = cleanup._welcome_email_html(
        "https://example.test", "https://example.test/unsubscribe?token=abc"
    )
    text = cleanup._welcome_email_text(
        "https://example.test", "https://example.test/unsubscribe?token=abc"
    )
    assert "Podslushano.nl" in html_body
    assert "Спасибо за подписку" in html_body
    assert "−26%" in html_body
    assert "Выбрать рекламный формат" in html_body
    assert "unsubscribe?token=abc" in html_body
    assert "−26%" in text
    assert "https://example.test/ads" in text


class FakeRequest:
    scheme = "https"
    host = "ads.example.test"

    def __init__(self, data=None, token=""):
        self._data = data or {}
        self.query = {"token": token} if token else {}

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


async def test_resend_payload_contains_working_unsubscribe_link() -> None:
    real_client_session = cleanup.aiohttp.ClientSession
    old_api_key = os.environ.get("RESEND_API_KEY")
    captured = {}

    class FakeResponse:
        status = 200

        async def text(self):
            return '{"id":"email_test"}'

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeSession:
        def __init__(self, *args, **kwargs):
            captured["session_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse()

    os.environ["RESEND_API_KEY"] = "re_test_key"
    cleanup.aiohttp.ClientSession = FakeSession
    try:
        sent = await cleanup._send_welcome_email(
            "buyer@example.com", "https://ads.example.test"
        )
        assert sent is True
        assert captured["url"] == "https://api.resend.com/emails"
        assert captured["headers"]["Authorization"] == "Bearer re_test_key"
        payload = captured["json"]
        assert payload["from"] == "Podslushano.nl <ads@podslushano.nl>"
        assert payload["to"] == ["buyer@example.com"]
        assert payload["subject"] == "Ваша скидка −26% активна — Podslushano.nl"
        unsubscribe_url = payload["headers"]["List-Unsubscribe"].strip("<>")
        assert unsubscribe_url.startswith(
            "https://ads.example.test/ads-newsletter/unsubscribe?token="
        )
        token = unsubscribe_url.split("token=", 1)[1]
        from urllib.parse import unquote

        assert season._unsubscribe_token_email(unquote(token)) == "buyer@example.com"
        assert unsubscribe_url in payload["html"]
        assert unsubscribe_url in payload["text"]
    finally:
        cleanup.aiohttp.ClientSession = real_client_session
        if old_api_key is None:
            os.environ.pop("RESEND_API_KEY", None)
        else:
            os.environ["RESEND_API_KEY"] = old_api_key


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


async def test_unsubscribe_get_and_post_deactivate_subscriber() -> None:
    token = season._issue_unsubscribe_token("buyer@example.com")

    page = await season.newsletter_unsubscribe_page(FakeRequest(token=token))
    assert page.status == 200
    assert "Отписаться от рассылки?" in page.text
    assert token in page.text

    invalid_page = await season.newsletter_unsubscribe_page(FakeRequest(token=token + "x"))
    assert invalid_page.status == 400

    subscriber = SimpleNamespace(email="buyer@example.com", is_active=True)
    committed = {"value": False}
    real_get_session = season.get_session

    class FakeDbSession:
        async def scalar(self, _statement):
            return subscriber

        async def commit(self):
            committed["value"] = True

    class FakeSessionContext:
        async def __aenter__(self):
            return FakeDbSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    season.get_session = lambda: FakeSessionContext()
    try:
        response = await season.newsletter_unsubscribe(
            FakeRequest({"token": token})
        )
        assert response.status == 200
        assert "Вы отписались" in response.text
        assert subscriber.is_active is False
        assert committed["value"] is True
    finally:
        season.get_session = real_get_session


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
    asyncio.run(test_resend_payload_contains_working_unsubscribe_link())
    asyncio.run(test_existing_subscriber_welcome())
    asyncio.run(test_unsubscribe_get_and_post_deactivate_subscriber())
    asyncio.run(test_page_injection())
    print(
        "[OK] Ads cleanup: centered gift + active badge + Resend welcome + unsubscribe"
    )


if __name__ == "__main__":
    main()
