"""OAuth fallback for the advertising Google Calendar integration.

Google Workspace/Cloud organizations can prohibit downloadable service-account
keys.  The original calendar integration only supported such a key.  This patch
keeps that mode for backwards compatibility and adds a standard user OAuth
refresh-token mode, which works with the existing Google account without
weakening the organization's service-account-key policy.

Required Railway variables for OAuth mode:
- GOOGLE_CALENDAR_ID
- GOOGLE_CALENDAR_OAUTH_CLIENT_ID
- GOOGLE_CALENDAR_OAUTH_CLIENT_SECRET
- GOOGLE_CALENDAR_OAUTH_REFRESH_TOKEN
"""
from __future__ import annotations

import asyncio
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

import config
from utils import ad_calendar

_OAUTH_TOKEN_URI = "https://oauth2.googleapis.com/token"
_oauth_credentials: Credentials | None = None
_oauth_lock = asyncio.Lock()
_original_access_token = ad_calendar._access_token


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _oauth_values() -> tuple[str, str, str]:
    return (
        _env("GOOGLE_CALENDAR_OAUTH_CLIENT_ID"),
        _env("GOOGLE_CALENDAR_OAUTH_CLIENT_SECRET"),
        _env("GOOGLE_CALENDAR_OAUTH_REFRESH_TOKEN"),
    )


def calendar_configuration_errors() -> list[str]:
    errors: list[str] = []
    if not config.GOOGLE_CALENDAR_ID:
        errors.append("не задана переменная GOOGLE_CALENDAR_ID")

    # Existing service-account deployments keep working unchanged.
    if config.GOOGLE_CALENDAR_CREDENTIALS_B64:
        return errors

    client_id, client_secret, refresh_token = _oauth_values()
    missing = []
    if not client_id:
        missing.append("GOOGLE_CALENDAR_OAUTH_CLIENT_ID")
    if not client_secret:
        missing.append("GOOGLE_CALENDAR_OAUTH_CLIENT_SECRET")
    if not refresh_token:
        missing.append("GOOGLE_CALENDAR_OAUTH_REFRESH_TOKEN")
    if missing:
        errors.append("не настроена OAuth-авторизация Google Calendar: " + ", ".join(missing))
    return errors


async def _oauth_access_token(force_refresh: bool = False) -> str:
    global _oauth_credentials
    client_id, client_secret, refresh_token = _oauth_values()
    if not (client_id and client_secret and refresh_token):
        raise RuntimeError("Google Calendar OAuth credentials are incomplete")

    async with _oauth_lock:
        # Rebuild credentials if the Railway token was rotated without a process
        # restart. This also makes local tests deterministic.
        if (
            _oauth_credentials is None
            or _oauth_credentials.refresh_token != refresh_token
            or _oauth_credentials.client_id != client_id
        ):
            _oauth_credentials = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri=_OAUTH_TOKEN_URI,
                client_id=client_id,
                client_secret=client_secret,
                scopes=ad_calendar._SCOPES,
            )

        if force_refresh or not _oauth_credentials.valid:
            await asyncio.to_thread(_oauth_credentials.refresh, Request())
        if not _oauth_credentials.token:
            raise RuntimeError("Google Calendar OAuth did not return an access token")
        return _oauth_credentials.token


async def _access_token(force_refresh: bool = False) -> str:
    # Prefer the old service-account mode when it is explicitly configured.
    if config.GOOGLE_CALENDAR_CREDENTIALS_B64:
        return await _original_access_token(force_refresh=force_refresh)
    return await _oauth_access_token(force_refresh=force_refresh)


def install_google_calendar_oauth() -> None:
    """Install the OAuth fallback into utils.ad_calendar once per process."""
    if getattr(ad_calendar, "_oauth_fallback_installed", False):
        return
    ad_calendar.calendar_configuration_errors = calendar_configuration_errors
    ad_calendar._access_token = _access_token
    ad_calendar._oauth_fallback_installed = True


install_google_calendar_oauth()
