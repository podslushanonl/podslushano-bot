"""Юзернеймы (@username) участников приложения: строго lowercase, латиница, цифры, «_» и «.», 3–24 символа.

Подбор свободного имени по имени (с транслитерацией) или почте, проверка ввода и заполнение при запуске.
"""
from __future__ import annotations

import os
import re

from sqlalchemy import select, update

MIN, MAX = 3, 24
_OK = re.compile(r"^[a-z0-9](?:[a-z0-9._]*[a-z0-9])?$")
# Имена сообщества и служебные — только для аккаунтов с галочкой (podslushano…) или вообще недоступны
_BRAND = "podslushano"
_RESERVED = {"admin", "administrator", "support", "moderator", "moderators", "help", "official", "root", "system",
             "app", "api", "settings", "login", "me", "user", "users", "null", "undefined"}
_TR = dict(zip("абвгдеёзийклмнопрстуфхыэ", "abvgdeezijklmnoprstufhye")) | {
    "ж": "zh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ь": "", "ю": "yu", "я": "ya",
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g"}


# Юзернеймы создателя: бессрочная галочка при запуске (database/db.py) и резерв — занять может только аккаунт
# с галочкой. Переопределяется переменной VERIFIED_USERNAMES (через запятую)
OWNERS = "alexmair"


def owners() -> list[str]:
    return [normalize(x) for x in os.getenv("VERIFIED_USERNAMES", OWNERS).split(",") if normalize(x)]


def normalize(raw: str | None) -> str:
    return str(raw or "").strip().lstrip("@").strip().lower()


def check(name: str, verified: bool = False) -> str | None:
    """Причина отказа или None, если юзернейм можно занять (уникальность проверяется отдельно)."""
    if not MIN <= len(name) <= MAX:
        return f"Юзернейм — от {MIN} до {MAX} символов."
    if not _OK.match(name) or ".." in name:
        return "Только латинские буквы, цифры, «_» и «.» (не в начале и не в конце)."
    if name in _RESERVED or ((name.startswith(_BRAND) or name in owners()) and not verified):
        return "Этот юзернейм зарезервирован."
    if name.isdigit():
        return "Юзернейм не может состоять только из цифр."
    return None


def _slug(text: str) -> str:
    out = "".join(_TR.get(ch, ch) for ch in (text or "").lower())
    out = re.sub(r"[^a-z0-9]+", "_", out).strip("_")
    return re.sub(r"_+", "_", out)[:18].strip("_")


def base_for(name: str | None, email: str | None, uid: int) -> str:
    """Основа юзернейма: имя латиницей («Алекс Петров» → alex_petrov), иначе начало почты, иначе user{id}."""
    for cand in (_slug(name or ""), _slug((email or "").split("@")[0])):
        if len(cand) >= MIN and not cand.isdigit() and check(cand) is None:
            return cand
    return f"user{uid}"


def is_auto(username: str | None, uid: int) -> bool:
    """Юзернейм выдан автоматически и ещё не выбран человеком (его можно пересобрать по имени)."""
    return not username or username == f"user{uid}"


def pick(base: str, taken: set[str], uid: int) -> str:
    if base not in taken:
        return base
    for suffix in (str(uid), *(str(n) for n in range(2, 1000))):
        cand = f"{base[:MAX - len(suffix) - 1]}_{suffix}"
        if cand not in taken:
            return cand
    return f"user{uid}"


async def assign(session, u, force: bool = False) -> None:
    """Выдаёт свободный юзернейм аккаунту без него (или с автоматическим — при force). Вызывать после flush."""
    from database.models import AppUser
    if u.username and not force:
        return
    base = base_for(u.name, u.email, u.id)
    like = (await session.execute(select(AppUser.username).where(
        AppUser.username.like(f"{base[:MAX]}%"), AppUser.id != u.id))).scalars()
    u.username = pick(base, set(like), u.id)


async def backfill(conn) -> None:
    """При запуске: юзернеймы всем аккаунтам, у которых их ещё нет."""
    from database.models import AppUser
    rows = (await conn.execute(select(AppUser.id, AppUser.name, AppUser.email).where(
        AppUser.username.is_(None)).order_by(AppUser.id))).all()
    if not rows:
        return
    taken = set((await conn.execute(select(AppUser.username).where(AppUser.username.is_not(None)))).scalars())
    for uid, name, email in rows:
        un = pick(base_for(name, email, uid), taken, uid)
        taken.add(un)
        await conn.execute(update(AppUser).where(AppUser.id == uid).values(username=un))
