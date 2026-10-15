"""API аккаунтов приложения podslushano.

Вход без пароля, аккаунт создаётся при первом входе:
- по коду: POST /api/app/auth/start {phone, cc} или {email} → 6-значный код SMS на номер
  (utils/sms.py) или письмом; {kind, to}. POST /api/app/auth/check {phone|email, code} → {token, user}.
  GET /api/app/auth/methods → {phone}: доступен ли сейчас вход по номеру.
  Старые адреса /auth/email и /auth/verify (только почта) оставлены для уже установленных версий;
- через Telegram: POST /api/app/auth/tg → {nonce, url}; человек открывает бота
  (t.me/<бот>?start=applogin_<nonce>), бот подтверждает; приложение опрашивает
  GET /api/app/auth/tg?nonce= → {token, user}, когда вход подтверждён.

Дальше запросы с заголовком Authorization: Bearer <token>:
GET/POST /api/app/me (имя, город, страна — только Нидерланды, Германия или Бельгия), POST /api/app/favorites {kind, key, title, on}.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from aiohttp import web
from sqlalchemy import delete, select, update

from database.db import get_session
from database.models import AppFavorite, AppLogin, AppUser, Country
from utils.email_templates import app_login_code
from utils.invoices import send_email_message
from utils import phone as phones, sms
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
    avatar = f"/api/app/user/{u.id}/avatar?v={u.avatar_v}" if u.avatar_v else ""
    return {"id": u.id, "name": u.name, "city": u.city, "country": u.country.value, "email": u.email or "",
            "phone": u.phone or "", "telegram": bool(u.tg_id), "bio": u.bio or "", "avatar": avatar}


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


# ---------------------------------------------------------------- вход по коду: телефон или почта

def _target(data: dict) -> tuple[str, str] | tuple[None, str]:
    """(kind, key) — куда слать код, или (None, текст ошибки)."""
    if data.get("phone"):
        p = phones.normalize(str(data.get("phone"))[:40], str(data.get("cc") or "")[:4])
        return ("phone", p) if p else (None, "Проверьте номер: нужен мобильный.")
    email = str(data.get("email") or "").strip().lower()[:200]
    return ("email", email) if EMAIL_RE.match(email) else (None, "Проверьте почту.")


async def auth_methods(request: web.Request) -> web.Response:
    return _json(request, {"ok": True, "phone": sms.available(), "email": True, "telegram": True})


async def _send(request: web.Request, kind: str, to: str, store: str = "") -> web.Response:
    """Код на номер или почту `to`. store — служебный вид записи (для привязки: «link-p:<id>»), иначе kind."""
    if kind == "phone" and not sms.available():
        return _err(request, "Вход по номеру временно недоступен. Войдите по почте.", 503)
    if _limited(f"app-ip:{_ip(request)}", 20) or _limited(f"app-{kind[0]}:{to}", 5):
        return _err(request, "Слишком много попыток. Попробуйте через час.", 429)
    store_kind, store_key = _store(kind, to, store)
    code = f"{secrets.randbelow(1_000_000):06d}"
    async with get_session() as session:
        await session.execute(delete(AppLogin).where(AppLogin.kind == store_kind, AppLogin.key == store_key))
        session.add(AppLogin(kind=store_kind, key=store_key, code_hash=_hash(store_key, code),
                             expires_at=_now() + timedelta(minutes=CODE_MIN)))
        await session.commit()
    if kind == "phone":
        if not await sms.send_code(to, code, CODE_MIN):
            return _err(request, "Не удалось отправить SMS. Проверьте номер или войдите по почте.", 502)
    else:
        ok, _ = await send_email_message(to, *app_login_code(code=code))
        if not ok:
            return _err(request, "Не удалось отправить письмо. Попробуйте позже.", 502)
    return _json(request, {"ok": True, "kind": kind, "to": to, "ttl": CODE_MIN * 60})


def _store(kind: str, to: str, link_user: int | str = "") -> tuple[str, str]:
    """Где лежит код: вход — (phone|email, номер/почта); привязка — (link-p|link-e, «<id аккаунта>:<номер/почта>»)."""
    return (f"link-{kind[0]}", f"{link_user}:{to}") if link_user else (kind, to)


async def _verify(request: web.Request, session, store_kind: str, store_key: str, raw_code) -> web.Response | AppLogin:
    """Проверка кода с лимитом попыток. AppLogin — код верный (ещё не погашен), иначе ответ с ошибкой."""
    code = "".join(ch for ch in str(raw_code or "") if ch.isdigit())[:6]
    row = (await session.execute(select(AppLogin).where(
        AppLogin.kind == store_kind, AppLogin.key == store_key, AppLogin.used.is_(False)))).scalar_one_or_none()
    if not row or row.expires_at < _now():
        return _err(request, "Код устарел. Запросите новый.")
    # Попытку списываем атомарно ДО проверки: параллельные запросы не обойдут лимит
    took = await session.execute(update(AppLogin).where(
        AppLogin.id == row.id, AppLogin.attempts < MAX_ATTEMPTS, AppLogin.used.is_(False))
        .values(attempts=AppLogin.attempts + 1))
    await session.commit()
    if took.rowcount != 1:
        return _err(request, "Слишком много попыток. Запросите новый код.", 429)
    if not secrets.compare_digest(row.code_hash, _hash(store_key, code)):
        return _err(request, "Неверный код.")
    return row


async def _claim(request: web.Request, session, row: AppLogin) -> web.Response | None:
    """Код одноразовый: только один запрос может его «погасить»."""
    claimed = await session.execute(update(AppLogin).where(AppLogin.id == row.id, AppLogin.used.is_(False))
                                    .values(used=True))
    if claimed.rowcount != 1:
        await session.rollback()
        return _err(request, "Код уже использован. Запросите новый.")
    return None


async def _check(request: web.Request, kind: str, key: str, raw_code) -> web.Response:
    async with get_session() as session:
        row = await _verify(request, session, kind, key, raw_code)
        if not isinstance(row, AppLogin):
            return row
        if (fail := await _claim(request, session, row)):
            return fail
        # 1) номер/почта уже есть у аккаунта — входим в него;
        # 2) нет, но человек уже вошёл (например, по почте) — записываем проверенный номер в его аккаунт, а не плодим второй;
        # 3) иначе — новый аккаунт
        col = AppUser.phone if kind == "phone" else AppUser.email
        u = (await session.execute(select(AppUser).where(col == key))).scalar_one_or_none()
        if not u:
            u = await _user(request, session)
            if u:
                setattr(u, kind, key)
                log.info("Вход: %s привязан(а) к уже открытому аккаунту %s", kind, u.id)
        if not u:
            u = AppUser(phone=key) if kind == "phone" else AppUser(email=key)
            session.add(u)
        u.last_seen = _now()
        await session.commit()
        return _json(request, _session(u))


# ---------------------------------------------------------------- привязка номера или почты к своему аккаунту

async def link_start(request: web.Request) -> web.Response:
    """POST /api/app/me/link/start {phone, cc} | {email} — код на новый номер или почту для привязки."""
    data = await _body(request)
    kind, to = _target(data)
    if not kind:
        return _err(request, to)
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите заново.", 401)
        if (me.phone if kind == "phone" else me.email) == to:
            return _err(request, "Уже привязан к вашему аккаунту.")
        await session.commit()
    return await _send(request, kind, to, me.id)


async def link_check(request: web.Request) -> web.Response:
    """POST /api/app/me/link/check {phone|email, code, move?}. Если номер или почта уже у другого аккаунта —
    после верного кода 409 {taken: {name}}; повтор с move=true переносит их сюда (тот аккаунт теряет этот способ входа)."""
    data = await _body(request)
    kind, to = _target(data)
    if not kind:
        return _err(request, to)
    async with get_session() as session:
        me = await _user(request, session)
        if not me:
            return _err(request, "Войдите заново.", 401)
        row = await _verify(request, session, *_store(kind, to, me.id), data.get("code"))
        if not isinstance(row, AppLogin):
            return row
        col = AppUser.phone if kind == "phone" else AppUser.email
        other = (await session.execute(select(AppUser).where(col == to, AppUser.id != me.id))).scalar_one_or_none()
        if other and data.get("move") is not True:
            # Код верный, но не гасим: человек подтвердит перенос и отправит его ещё раз
            await session.commit()
            what = "Этот номер" if kind == "phone" else "Эта почта"
            return _json(request, {"ok": False, "error": f"{what} уже привязан(а) к другому аккаунту.",
                                   "taken": {"name": other.name or ""}}, 409)
        if (fail := await _claim(request, session, row)):
            return fail
        if other:
            setattr(other, kind, None)
            await session.flush()      # освобождаем уникальное значение до записи в свой аккаунт
            log.info("Привязка: %s перенесён(а) с аккаунта %s на %s", kind, other.id, me.id)
        setattr(me, kind, to)
        await session.commit()
        return _json(request, {"ok": True, "user": user_json(me)})


async def auth_start(request: web.Request) -> web.Response:
    kind, key = _target(await _body(request))
    return await _send(request, kind, key) if kind else _err(request, key)


async def auth_check(request: web.Request) -> web.Response:
    data = await _body(request)
    kind, key = _target(data)
    return await _check(request, kind, key, data.get("code")) if kind else _err(request, key)


async def auth_email(request: web.Request) -> web.Response:
    """Старый адрес: только почта."""
    data = await _body(request)
    kind, key = _target({"email": data.get("email")})
    return await _send(request, kind, key) if kind else _err(request, key)


async def auth_verify(request: web.Request) -> web.Response:
    data = await _body(request)
    kind, key = _target({"email": data.get("email")})
    return await _check(request, kind, key, data.get("code")) if kind else _err(request, key)


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
        claimed = await session.execute(update(AppLogin).where(AppLogin.id == row.id, AppLogin.used.is_(False))
                                        .values(used=True))
        if claimed.rowcount != 1:
            await session.rollback()
            return _err(request, "Ссылка устарела. Начните вход заново.", 410)
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
            if "country" in data:
                try:
                    u.country = Country.parse(data.get("country"))
                except ValueError:
                    return _err(request, "Страна: Нидерланды, Германия или Бельгия.")
            if "bio" in data:
                bio = " ".join(str(data.get("bio") or "").split())[:160]
                if bio:
                    from utils.community import check_text
                    reason = check_text(u, bio, 160)
                    if reason:
                        return _err(request, reason)
                u.bio = bio
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


async def set_avatar(request: web.Request) -> web.Response:
    """POST /api/app/me/avatar {photo: data:..., crop?: {x, y, w, h} в долях} — новое фото профиля (квадрат 512 px
    по выбранной рамке), {photo: ""} — убрать."""
    from utils.market import _read_json, prepare_avatar
    data = await _read_json(request)
    async with get_session() as session:
        u = await _user(request, session)
        if not u:
            return _err(request, "Войдите заново.", 401)
        raw = str(data.get("photo") or "")
        if raw:
            crop = data.get("crop")
            jpeg = prepare_avatar(raw, crop=crop if isinstance(crop, dict) else None)
            if not jpeg:
                return _err(request, "Не получилось прочитать фото. Попробуйте другое.")
            u.avatar, u.avatar_v = jpeg, (u.avatar_v or 0) + 1
        else:
            u.avatar, u.avatar_v = None, 0
        await session.commit()
        return _json(request, {"ok": True, "user": user_json(u)})


def install_routes(app: web.Application) -> None:
    app.router.add_post("/api/app/me/avatar", set_avatar)
    app.router.add_post("/api/app/me/link/start", link_start)
    app.router.add_post("/api/app/me/link/check", link_check)
    app.router.add_get("/api/app/auth/methods", auth_methods)
    app.router.add_post("/api/app/auth/start", auth_start)
    app.router.add_post("/api/app/auth/check", auth_check)
    app.router.add_post("/api/app/auth/email", auth_email)
    app.router.add_post("/api/app/auth/verify", auth_verify)
    app.router.add_post("/api/app/auth/tg", auth_tg_start)
    app.router.add_get("/api/app/auth/tg", auth_tg_poll)
    app.router.add_get("/api/app/me", me)
    app.router.add_post("/api/app/me", me)
    app.router.add_post("/api/app/favorites", favorite)
