"""API аккаунтов приложения podslushano.

Вход без пароля, аккаунт создаётся при первом входе:
- по почте: POST /api/app/auth/email {email} → письмо с 6-значным кодом;
  POST /api/app/auth/verify {email, code} → {token, user};
- через Telegram: POST /api/app/auth/tg → {nonce, url}; человек открывает бота
  (t.me/<бот>?start=applogin_<nonce>), бот подтверждает; приложение опрашивает
  GET /api/app/auth/tg?nonce= → {token, user}, когда вход подтверждён.

Дальше запросы с заголовком Authorization: Bearer <token>:
GET/POST /api/app/me (имя, город), POST /api/app/favorites {kind, key, title, on}.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from aiohttp import web
from sqlalchemy import delete, select

from database.db import get_session
from database.models import AppFavorite, AppLogin, AppUser
from utils.email_templates import app_login_code
from utils.invoices import send_email_message
from utils.newsletter import _limited
from utils.site_api import EMAIL_RE, _body, _err, _json, make_token, read_token

log = logging.getLogger(__name__)

TOKEN_DAYS = 180
CODE_MIN = 15
TG_MIN = 10
MAX_ATTEMPTS = 5
BOT_LINK = "https://t.me/podslushano_nl_bot"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(email: str, code: str) -> str:
    return hashlib.sha256(f"{email}:{code}".encode()).hexdigest()


def _ip(request: web.Request) -> str:
    return request.headers.get("X-Forwarded-For", request.remote or "").split(",")[0].strip()


def user_json(u: AppUser) -> dict:
    return {"id": u.id, "name": u.name, "city": u.city, "email": u.email or "", "telegram": bool(u.tg_id)}


def _session(u: AppUser) -> dict:
    return {"ok": True, "token": make_token({"k": "app", "u": u.id}, TOKEN_DAYS * 86400), "user": user_json(u)}


async def _user(request: web.Request, session) -> AppUser | None:
    auth = request.headers.get("Authorization", "")
    data = read_token(auth[7:] if auth.startswith("Bearer ") else "", "app")
    if not data:
        return None
    u = await session.get(AppUser, int(data.get("u") or 0))
    if u:
        u.last_seen = _now()
    return u


# ---------------------------------------------------------------- вход по почте

async def auth_email(request: web.Request) -> web.Response:
    data = await _body(request)
    email = str(data.get("email") or "").strip().lower()[:200]
    if not EMAIL_RE.match(email):
        return _err(request, "Проверьте почту.")
    if _limited(f"app-ip:{_ip(request)}", 20) or _limited(f"app-e:{email}", 5):
        return _err(request, "Слишком много попыток. Попробуйте через час.", 429)
    code = f"{secrets.randbelow(1_000_000):06d}"
    async with get_session() as session:
        await session.execute(delete(AppLogin).where(AppLogin.kind == "email", AppLogin.key == email))
        session.add(AppLogin(kind="email", key=email, code_hash=_hash(email, code),
                             expires_at=_now() + timedelta(minutes=CODE_MIN)))
        await session.commit()
    ok, _ = await send_email_message(email, *app_login_code(code=code))
    if not ok:
        return _err(request, "Не удалось отправить письмо. Попробуйте позже.", 502)
    return _json(request, {"ok": True})


async def auth_verify(request: web.Request) -> web.Response:
    data = await _body(request)
    email = str(data.get("email") or "").strip().lower()[:200]
    code = "".join(ch for ch in str(data.get("code") or "") if ch.isdigit())[:6]
    async with get_session() as session:
        row = (await session.execute(select(AppLogin).where(
            AppLogin.kind == "email", AppLogin.key == email, AppLogin.used.is_(False)))).scalar_one_or_none()
        if not row or row.expires_at < _now():
            return _err(request, "Код устарел. Запросите новый.")
        if row.attempts >= MAX_ATTEMPTS:
            return _err(request, "Слишком много попыток. Запросите новый код.", 429)
        if not secrets.compare_digest(row.code_hash, _hash(email, code)):
            row.attempts += 1
            await session.commit()
            return _err(request, "Неверный код.")
        row.used = True
        u = (await session.execute(select(AppUser).where(AppUser.email == email))).scalar_one_or_none()
        if not u:
            u = AppUser(email=email)
            session.add(u)
        u.last_seen = _now()
        await session.commit()
        return _json(request, _session(u))


# ---------------------------------------------------------------- вход через Telegram

async def auth_tg_start(request: web.Request) -> web.Response:
    if _limited(f"app-tg:{_ip(request)}", 30):
        return _err(request, "Слишком много попыток. Попробуйте позже.", 429)
    nonce = secrets.token_urlsafe(16)
    async with get_session() as session:
        session.add(AppLogin(kind="tg", key=nonce, expires_at=_now() + timedelta(minutes=TG_MIN)))
        await session.commit()
    return _json(request, {"ok": True, "nonce": nonce, "url": f"{BOT_LINK}?start=applogin_{nonce}"})


async def confirm_tg(nonce: str, tg_id: int, name: str) -> bool:
    """Вызывается ботом, когда человек открыл ссылку входа. False — ссылка устарела."""
    async with get_session() as session:
        row = (await session.execute(select(AppLogin).where(
            AppLogin.kind == "tg", AppLogin.key == nonce[:200], AppLogin.used.is_(False)))).scalar_one_or_none()
        if not row or row.expires_at < _now() or row.tg_id:
            return False
        row.tg_id, row.tg_name = tg_id, (name or "")[:80]
        await session.commit()
        return True


async def auth_tg_poll(request: web.Request) -> web.Response:
    nonce = request.query.get("nonce", "")[:200]
    async with get_session() as session:
        row = (await session.execute(select(AppLogin).where(
            AppLogin.kind == "tg", AppLogin.key == nonce))).scalar_one_or_none()
        if not row or row.used or row.expires_at < _now():
            return _err(request, "Ссылка устарела. Начните вход заново.", 410)
        if not row.tg_id:
            return _json(request, {"ok": True, "pending": True})
        row.used = True
        u = (await session.execute(select(AppUser).where(AppUser.tg_id == row.tg_id))).scalar_one_or_none()
        if not u:
            u = AppUser(tg_id=row.tg_id, name=row.tg_name)
            session.add(u)
        u.last_seen = _now()
        await session.commit()
        return _json(request, _session(u))


# ---------------------------------------------------------------- профиль и избранное

async def me(request: web.Request) -> web.Response:
    async with get_session() as session:
        u = await _user(request, session)
        if not u:
            return _err(request, "Войдите заново.", 401)
        if request.method == "POST":
            data = await _body(request)
            if "name" in data:
                u.name = str(data.get("name") or "").strip()[:80]
            if "city" in data:
                u.city = str(data.get("city") or "").strip()[:80]
        favs = (await session.execute(select(AppFavorite).where(AppFavorite.user_id == u.id)
                                      .order_by(AppFavorite.id.desc()))).scalars().all()
        await session.commit()
        return _json(request, {"ok": True, "user": user_json(u),
                               "favorites": [{"kind": f.kind, "key": f.key, "title": f.title} for f in favs]})


async def favorite(request: web.Request) -> web.Response:
    data = await _body(request)
    kind = str(data.get("kind") or "event")[:20]
    key = str(data.get("key") or "").strip()[:120]
    if not key:
        return _err(request, "Нет ключа.")
    async with get_session() as session:
        u = await _user(request, session)
        if not u:
            return _err(request, "Войдите заново.", 401)
        q = select(AppFavorite).where(AppFavorite.user_id == u.id, AppFavorite.kind == kind, AppFavorite.key == key)
        row = (await session.execute(q)).scalar_one_or_none()
        if data.get("on", True) and not row:
            session.add(AppFavorite(user_id=u.id, kind=kind, key=key, title=str(data.get("title") or "")[:200]))
        elif not data.get("on", True) and row:
            await session.delete(row)
        await session.commit()
    return _json(request, {"ok": True})


def install_routes(app: web.Application) -> None:
    app.router.add_post("/api/app/auth/email", auth_email)
    app.router.add_post("/api/app/auth/verify", auth_verify)
    app.router.add_post("/api/app/auth/tg", auth_tg_start)
    app.router.add_get("/api/app/auth/tg", auth_tg_poll)
    app.router.add_get("/api/app/me", me)
    app.router.add_post("/api/app/me", me)
    app.router.add_post("/api/app/favorites", favorite)
