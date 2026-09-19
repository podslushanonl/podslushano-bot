"""Одноразовое OAuth-подключение Gmail для чтения ответов рекламодателей.

Права строго read-only: https://www.googleapis.com/auth/gmail.readonly

Схема:
1. Администратор пишет /gmailconnect в Telegram.
2. Бот создаёт одноразовый state и выдаёт ссылку Google OAuth.
3. Google возвращает code на публичный callback Railway.
4. Сервер проверяет state, e-mail аккаунта и доступ Gmail API.
5. Refresh-token хранится в Railway DB в зашифрованном виде.
6. На старте процесса токен подставляется в GOOGLE_GMAIL_OAUTH_REFRESH_TOKEN,
   который уже читает ad_material_reminder_runtime.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import os
import secrets
import time
from datetime import datetime
from urllib.parse import urlencode

import aiohttp
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiohttp import web
from cryptography.fernet import Fernet, InvalidToken

import config
from database.ad_sales_models import AdGmailConnection
from database.db import get_session
from database.models import Meta

log = logging.getLogger(__name__)
router = Router()

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
CALLBACK_PATH = "/admin/gmail/oauth/callback"
_STATE_PREFIX = "gmailoauth:"
_STATE_TTL_SECONDS = 15 * 60
_CONNECTION_ID = 1


def _client_id() -> str:
    return (
        os.getenv("GOOGLE_GMAIL_OAUTH_CLIENT_ID", "").strip()
        or os.getenv("GOOGLE_CALENDAR_OAUTH_CLIENT_ID", "").strip()
    )


def _client_secret() -> str:
    return (
        os.getenv("GOOGLE_GMAIL_OAUTH_CLIENT_SECRET", "").strip()
        or os.getenv("GOOGLE_CALENDAR_OAUTH_CLIENT_SECRET", "").strip()
    )


def _redirect_uri() -> str:
    override = os.getenv("GOOGLE_GMAIL_OAUTH_REDIRECT_URI", "").strip()
    if override:
        return override
    return f"{config.WEBHOOK_BASE_URL.rstrip('/')}{CALLBACK_PATH}" if config.WEBHOOK_BASE_URL else ""


def _expected_email() -> str:
    return (os.getenv("GOOGLE_GMAIL_EXPECTED_EMAIL", "").strip() or config.COMPANY_EMAIL).lower()


def _oauth_configuration_errors() -> list[str]:
    errors: list[str] = []
    if not _client_id():
        errors.append("не задан OAuth Client ID")
    if not _client_secret():
        errors.append("не задан OAuth Client Secret")
    if not _redirect_uri():
        errors.append("не определён публичный callback URL")
    if not (os.getenv("GMAIL_TOKEN_ENCRYPTION_KEY", "").strip() or config.BOT_TOKEN):
        errors.append("не задан ключ шифрования Gmail token")
    return errors


def _fernet() -> Fernet:
    secret = os.getenv("GMAIL_TOKEN_ENCRYPTION_KEY", "").strip() or config.BOT_TOKEN
    if not secret:
        raise RuntimeError("GMAIL_TOKEN_ENCRYPTION_KEY is missing")
    digest = hashlib.sha256(("podslushano:gmail:" + secret).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def _decrypt_token(value: str) -> str | None:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        log.error("Не удалось расшифровать Gmail refresh-token: %s", exc)
        return None


def _state_key(state: str) -> str:
    return f"{_STATE_PREFIX}{state}"


async def _create_state(admin_id: int) -> str:
    state = secrets.token_urlsafe(18)
    expires = int(time.time()) + _STATE_TTL_SECONDS
    async with get_session() as session:
        await session.merge(Meta(key=_state_key(state), value=f"{admin_id}:{expires}"))
        await session.commit()
    return state


async def _consume_state(state: str) -> int | None:
    if not state or len(state) > 32:
        return None
    async with get_session() as session:
        row = await session.get(Meta, _state_key(state))
        if row is None:
            return None
        raw = row.value or ""
        await session.delete(row)
        await session.commit()
    try:
        admin_raw, expiry_raw = raw.split(":", 1)
        admin_id = int(admin_raw)
        expiry = int(expiry_raw)
    except (ValueError, TypeError):
        return None
    if expiry < int(time.time()) or admin_id not in config.ADMIN_IDS:
        return None
    return admin_id


async def _connection() -> AdGmailConnection | None:
    async with get_session() as session:
        return await session.get(AdGmailConnection, _CONNECTION_ID)


async def get_saved_refresh_token() -> str | None:
    row = await _connection()
    if row is None:
        return None
    return _decrypt_token(row.refresh_token_encrypted)


async def install_saved_refresh_token() -> str | None:
    """Подставляет сохранённый токен в существующий Gmail-checker после рестарта."""
    row = await _connection()
    if row is None:
        return None
    token = _decrypt_token(row.refresh_token_encrypted)
    if not token:
        return None
    os.environ["GOOGLE_GMAIL_OAUTH_REFRESH_TOKEN"] = token
    return row.email


async def _save_connection(email_address: str, refresh_token: str, scope: str) -> None:
    encrypted = _encrypt_token(refresh_token)
    async with get_session() as session:
        row = await session.get(AdGmailConnection, _CONNECTION_ID)
        if row is None:
            row = AdGmailConnection(
                id=_CONNECTION_ID,
                email=email_address,
                refresh_token_encrypted=encrypted,
                scope=scope,
            )
            session.add(row)
        else:
            row.email = email_address
            row.refresh_token_encrypted = encrypted
            row.scope = scope
            row.connected_at = datetime.utcnow()
        await session.commit()
    # Сразу активируем подключение в текущем процессе; рестарт не требуется.
    os.environ["GOOGLE_GMAIL_OAUTH_REFRESH_TOKEN"] = refresh_token


async def _authorization_url(admin_id: int) -> str:
    state = await _create_state(admin_id)
    params = {
        "client_id": _client_id(),
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": GMAIL_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
        "login_hint": _expected_email(),
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def _page(title: str, body: str, ok: bool = False) -> str:
    mark = "✅" if ok else "⚠️"
    safe_title = html.escape(title)
    return f"""<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"robots\" content=\"noindex,nofollow\">
<title>{safe_title} — Podslushano.nl</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif;background:#f4f4f2;margin:0;min-height:100vh;display:grid;place-items:center;color:#171717}}
.card{{width:min(520px,calc(100% - 32px));box-sizing:border-box;background:white;border:1px solid #deded8;border-radius:24px;padding:34px;box-shadow:0 18px 50px rgba(0,0,0,.08)}}
.icon{{font-size:42px}}h1{{font-size:26px;margin:14px 0 10px}}p{{line-height:1.55;color:#555}}a{{display:inline-block;margin-top:14px;background:#171717;color:#fff;text-decoration:none;padding:13px 18px;border-radius:999px;font-weight:700}}
</style></head><body><main class=\"card\"><div class=\"icon\">{mark}</div><h1>{safe_title}</h1>{body}<a href=\"{html.escape(config.BOT_URL, quote=True)}\">Вернуться в Telegram</a></main></body></html>"""


async def _notify_admin(bot, admin_id: int, text: str) -> None:
    try:
        await bot.send_message(admin_id, text)
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось уведомить администратора о Gmail OAuth: %s", exc)


@router.message(Command("gmailconnect"))
async def gmail_connect(message: Message) -> None:
    if message.from_user is None or message.from_user.id not in config.ADMIN_IDS:
        return
    errors = _oauth_configuration_errors()
    if errors:
        await message.answer("❌ Gmail OAuth пока не готов:\n• " + "\n• ".join(errors))
        return
    row = await _connection()
    url = await _authorization_url(message.from_user.id)
    status = (
        f"Сейчас подключён: <b>{html.escape(row.email)}</b>. Можно переподключить доступ."
        if row else
        f"Подключим <b>{html.escape(_expected_email())}</b> только на чтение писем."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔐 Подключить Gmail", url=url)
    ]])
    await message.answer(
        "📬 <b>Gmail для рекламных материалов</b>\n\n"
        f"{status}\n\n"
        "Google попросит только право чтения Gmail. Бот не сможет отправлять, удалять "
        "или изменять письма. Одноразовая ссылка действует 15 минут.",
        reply_markup=kb,
    )


async def gmail_oauth_callback(request: web.Request) -> web.Response:
    state = (request.query.get("state") or "").strip()
    admin_id = await _consume_state(state)
    if admin_id is None:
        return web.Response(
            text=_page("Ссылка недействительна", "<p>Одноразовая ссылка истекла или уже была использована. Запустите <b>/gmailconnect</b> ещё раз.</p>"),
            content_type="text/html", status=400,
        )
    bot = request.app["bot"]
    oauth_error = (request.query.get("error") or "").strip()
    if oauth_error:
        await _notify_admin(bot, admin_id, f"❌ Gmail не подключён: Google вернул {html.escape(oauth_error)}")
        return web.Response(
            text=_page("Доступ не предоставлен", "<p>Google не передал разрешение на чтение Gmail. Ничего не было сохранено.</p>"),
            content_type="text/html", status=400,
        )
    code = (request.query.get("code") or "").strip()
    if not code:
        return web.Response(
            text=_page("Не получен код Google", "<p>Повторите подключение через <b>/gmailconnect</b>.</p>"),
            content_type="text/html", status=400,
        )

    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": _client_id(),
                    "client_secret": _client_secret(),
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": _redirect_uri(),
                },
            ) as response:
                token_payload = await response.json(content_type=None)
                if response.status >= 300:
                    detail = token_payload.get("error_description") or token_payload.get("error") or f"HTTP {response.status}"
                    await _notify_admin(bot, admin_id, f"❌ Gmail OAuth: не удалось получить токен — {html.escape(str(detail)[:500])}")
                    return web.Response(
                        text=_page("Google не выдал токен", f"<p>{html.escape(str(detail))}</p><p>Если указано <b>redirect_uri_mismatch</b>, нужно добавить callback URL в OAuth Client Google Cloud.</p>"),
                        content_type="text/html", status=400,
                    )
            access_token = (token_payload.get("access_token") or "").strip()
            refresh_token = (token_payload.get("refresh_token") or "").strip()
            granted_scope = (token_payload.get("scope") or "").strip()
            if not access_token or not refresh_token:
                await _notify_admin(bot, admin_id, "❌ Gmail OAuth не вернул refresh-token. Запусти /gmailconnect ещё раз.")
                return web.Response(
                    text=_page("Не получен постоянный доступ", "<p>Google не вернул refresh-token. Запустите <b>/gmailconnect</b> ещё раз и подтвердите доступ.</p>"),
                    content_type="text/html", status=400,
                )
            headers = {"Authorization": f"Bearer {access_token}"}
            async with session.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                headers=headers,
            ) as response:
                profile_text = await response.text()
                if response.status >= 300:
                    await _notify_admin(
                        bot, admin_id,
                        "❌ Gmail API недоступен после OAuth. Проверь, что Gmail API включён в Google Cloud project.",
                    )
                    return web.Response(
                        text=_page(
                            "Gmail API не отвечает",
                            "<p>Авторизация Google прошла, но Gmail API не разрешил чтение. Обычно нужно включить <b>Gmail API</b> в том же Google Cloud project, где создан OAuth Client.</p>",
                        ),
                        content_type="text/html", status=400,
                    )
                profile = json.loads(profile_text)
            email_address = (profile.get("emailAddress") or "").strip().lower()
            expected = _expected_email()
            if email_address != expected:
                await _notify_admin(
                    bot, admin_id,
                    f"❌ Gmail не подключён: выбран {html.escape(email_address or 'неизвестный аккаунт')}, нужен {html.escape(expected)}.",
                )
                return web.Response(
                    text=_page(
                        "Выбран другой Google-аккаунт",
                        f"<p>Вы вошли как <b>{html.escape(email_address or 'неизвестный аккаунт')}</b>.</p><p>Нужен <b>{html.escape(expected)}</b>. Запустите <b>/gmailconnect</b> заново и выберите правильный аккаунт.</p>",
                    ),
                    content_type="text/html", status=400,
                )
            if GMAIL_SCOPE not in granted_scope.split():
                await _notify_admin(bot, admin_id, "❌ Gmail OAuth завершился без gmail.readonly scope.")
                return web.Response(
                    text=_page("Не выдано право чтения Gmail", "<p>Google не подтвердил необходимый read-only scope. Ничего не сохранено.</p>"),
                    content_type="text/html", status=400,
                )
            await _save_connection(email_address, refresh_token, granted_scope)
    except Exception as exc:  # noqa: BLE001
        log.exception("Ошибка Gmail OAuth callback: %s", exc)
        await _notify_admin(bot, admin_id, "❌ Ошибка при подключении Gmail. Токен не сохранён.")
        return web.Response(
            text=_page("Ошибка подключения", "<p>Не удалось завершить подключение. Повторите <b>/gmailconnect</b>.</p>"),
            content_type="text/html", status=500,
        )

    await _notify_admin(
        bot, admin_id,
        "✅ <b>Gmail подключён</b>\n\n"
        f"Ящик: {html.escape(email_address)}\n"
        "Доступ: только чтение. Теперь перед каждым рекламным напоминанием бот сам "
        "проверяет ответы, вложения и ссылки на материалы.",
    )
    return web.Response(
        text=_page(
            "Gmail подключён",
            f"<p><b>{html.escape(email_address)}</b> подключён только на чтение.</p><p>Бот теперь автоматически увидит ответы рекламодателей, вложения и ссылки на материалы и остановит последующие напоминания.</p>",
            ok=True,
        ),
        content_type="text/html",
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
    )


async def start_webserver_with_gmail(bot):
    """Добавляет OAuth callback к существующему aiohttp-приложению без копии роутов."""
    from utils import webserver as ws

    original_application = ws.web.Application

    def application_factory(*args, **kwargs):
        app = original_application(*args, **kwargs)
        app.router.add_get(CALLBACK_PATH, gmail_oauth_callback)
        return app

    ws.web.Application = application_factory
    try:
        return await ws.start_webserver(bot)
    finally:
        ws.web.Application = original_application
