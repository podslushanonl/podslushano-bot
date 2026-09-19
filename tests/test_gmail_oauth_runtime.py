"""Focused checks for Gmail read-only OAuth used by ad reminders."""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_TOKEN", "123456:test-token")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ.setdefault("GMAIL_TOKEN_ENCRYPTION_KEY", "test-gmail-encryption-key")
os.environ.setdefault("GOOGLE_CALENDAR_OAUTH_CLIENT_ID", "client-id.apps.googleusercontent.com")
os.environ.setdefault("GOOGLE_CALENDAR_OAUTH_CLIENT_SECRET", "client-secret")

import config  # noqa: E402
import gmail_oauth_runtime as gmail  # noqa: E402


def test_security_contract() -> None:
    assert gmail.GMAIL_SCOPE == "https://www.googleapis.com/auth/gmail.readonly"
    assert "modify" not in gmail.GMAIL_SCOPE
    assert "send" not in gmail.GMAIL_SCOPE

    token = "1//refresh-token-example"
    encrypted = gmail._encrypt_token(token)
    assert encrypted != token
    assert gmail._decrypt_token(encrypted) == token

    old_base = config.WEBHOOK_BASE_URL
    config.WEBHOOK_BASE_URL = "https://worker.example.test"
    try:
        assert gmail._redirect_uri() == (
            "https://worker.example.test/admin/gmail/oauth/callback"
        )
    finally:
        config.WEBHOOK_BASE_URL = old_base

    assert gmail._expected_email() == config.COMPANY_EMAIL.lower()


async def test_web_route_injection() -> None:
    from utils import webserver as ws

    original_start = ws.start_webserver
    captured = {}

    async def fake_start(_bot):
        app = ws.web.Application()
        captured["app"] = app
        return app

    ws.start_webserver = fake_start
    try:
        result = await gmail.start_webserver_with_gmail(object())
    finally:
        ws.start_webserver = original_start

    assert result is captured["app"]
    paths = {getattr(route.resource, "canonical", "") for route in result.router.routes()}
    assert gmail.CALLBACK_PATH in paths


def main() -> None:
    test_security_contract()
    asyncio.run(test_web_route_injection())
    print("[OK] Gmail OAuth: read-only scope + encrypted token + callback route")


if __name__ == "__main__":
    main()
