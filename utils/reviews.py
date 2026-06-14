"""Отзывы и рейтинги специалистов.

Ключ специалиста — стабильная строка (имя+контакт), чтобы оценки переживали
пере-засев базы (где меняются числовые id).
"""
from sqlalchemy import func, select

from database.db import get_session
from database.models import BotUser, Review


def specialist_key(name: str | None, contact: str | None) -> str:
    return f"{(name or '').strip().lower()}|{(contact or '').strip().lower()}"


async def ratings_for(keys: list[str]) -> dict[str, tuple[float, int]]:
    """Для списка ключей возвращает {key: (средняя_оценка, число_отзывов)}."""
    keys = [k for k in set(keys) if k]
    if not keys:
        return {}
    async with get_session() as session:
        rows = (
            await session.execute(
                select(Review.spec_key, func.avg(Review.rating), func.count())
                .where(Review.spec_key.in_(keys))
                .group_by(Review.spec_key)
            )
        ).all()
    return {k: (round(float(avg), 1), int(cnt)) for k, avg, cnt in rows}


async def texts_for(keys: list[str], per_key: int = 2) -> dict[str, list[tuple[int, str]]]:
    """Для списка ключей возвращает последние отзывы с текстом:
    {key: [(оценка, текст), ...]} — не больше per_key на специалиста."""
    keys = [k for k in set(keys) if k]
    if not keys:
        return {}
    async with get_session() as session:
        rows = (
            await session.execute(
                select(Review.spec_key, Review.rating, Review.text)
                .where(Review.spec_key.in_(keys), Review.text.is_not(None), Review.text != "")
                .order_by(Review.created_at.desc())
            )
        ).all()
    out: dict[str, list[tuple[int, str]]] = {}
    for key, rating, text in rows:
        bucket = out.setdefault(key, [])
        if len(bucket) < per_key:
            bucket.append((int(rating), text))
    return out


def rating_badge(rating: tuple[float, int] | None) -> str:
    """Текстовый бейдж рейтинга: '⭐ 4.6 (12)' или '' если отзывов нет."""
    if not rating or rating[1] == 0:
        return ""
    avg, cnt = rating
    return f"⭐ {avg} ({cnt})"


async def recent_reviews(limit: int = 12) -> list[dict]:
    """Последние отзывы с данными об авторе — для просмотра админом.

    Имя специалиста берём из ключа (часть до «|»). Автор подтягивается из
    таблицы пользователей (если он там есть) — отдаём имя и @username.
    """
    async with get_session() as session:
        rows = (
            await session.execute(
                select(
                    Review.spec_key,
                    Review.rating,
                    Review.text,
                    Review.user_id,
                    Review.created_at,
                    BotUser.username,
                    BotUser.first_name,
                )
                .outerjoin(BotUser, BotUser.user_id == Review.user_id)
                .order_by(Review.created_at.desc())
                .limit(limit)
            )
        ).all()
    out: list[dict] = []
    for spec_key, rating, text, user_id, created_at, username, first_name in rows:
        out.append(
            {
                "spec_name": (spec_key or "").split("|", 1)[0] or "—",
                "rating": int(rating),
                "text": text,
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "created_at": created_at,
            }
        )
    return out


async def add_or_update_review(spec_key: str, user_id: int, rating: int, text: str | None) -> None:
    async with get_session() as session:
        existing = (
            await session.scalars(
                select(Review).where(Review.spec_key == spec_key, Review.user_id == user_id)
            )
        ).first()
        if existing is not None:
            existing.rating = rating
            if text is not None:
                existing.text = text
        else:
            session.add(Review(spec_key=spec_key, user_id=user_id, rating=rating, text=text))
        await session.commit()


async def set_review_text(spec_key: str, user_id: int, text: str) -> None:
    async with get_session() as session:
        existing = (
            await session.scalars(
                select(Review).where(Review.spec_key == spec_key, Review.user_id == user_id)
            )
        ).first()
        if existing is not None:
            existing.text = text
            await session.commit()
