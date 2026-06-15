"""Простая аналитика: лог событий и сводка для админа."""
import logging

from sqlalchemy import func, select

from database.db import get_session
from database.models import BotUser, Event, Review, Specialist, Submission

log = logging.getLogger(__name__)

_SUB_TITLES = {"story": "истории", "question": "вопросы", "video": "видео", "ad": "реклама"}


async def log_event(type_: str, key: str | None = None) -> None:
    """Записывает событие (никогда не мешает работе при ошибке)."""
    try:
        async with get_session() as session:
            session.add(Event(type=type_, key=(key or "")[:100]))
            await session.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось записать событие %s: %s", type_, e)


async def gather_stats() -> str:
    """Собирает текстовую сводку статистики."""
    async with get_session() as session:
        users = await session.scalar(select(func.count()).select_from(BotUser)) or 0
        active_users = await session.scalar(
            select(func.count()).select_from(BotUser).where(BotUser.is_blocked.is_(False))
        ) or 0
        searches = await session.scalar(
            select(func.count()).select_from(Event).where(Event.type == "search")
        ) or 0
        search_miss_total = await session.scalar(
            select(func.count()).select_from(Event).where(Event.type == "search_miss")
        ) or 0
        payments = await session.scalar(
            select(func.count()).select_from(Event).where(Event.type == "payment")
        ) or 0

        async def _count(ev_type: str) -> int:
            return await session.scalar(
                select(func.count()).select_from(Event).where(Event.type == ev_type)
            ) or 0

        ai_chats = await _count("ai")      # вопросы боту (ИИ)
        letters = await _count("letter")   # разбор писем
        salary = await _count("salary")    # калькулятор зарплаты
        guides = await _count("guide")     # «Полезное»
        top_guides = (
            await session.execute(
                select(Event.key, func.count())
                .where(Event.type == "guide", Event.key != "", Event.key != "menu")
                .group_by(Event.key)
                .order_by(func.count().desc())
                .limit(5)
            )
        ).all()
        reviews = await session.scalar(select(func.count()).select_from(Review)) or 0
        specs_active = await session.scalar(
            select(func.count()).select_from(Specialist).where(Specialist.status == "active")
        ) or 0
        specs_paid = await session.scalar(
            select(func.count()).select_from(Specialist).where(Specialist.source == "self")
        ) or 0
        top_cats = (
            await session.execute(
                select(Event.key, func.count())
                .where(Event.type == "search", Event.key != "")
                .group_by(Event.key)
                .order_by(func.count().desc())
                .limit(10)
            )
        ).all()
        # Спрос без предложения: что ищут, но активных карточек в категории нет
        search_by_cat = (
            await session.execute(
                select(Event.key, func.count())
                .where(Event.type == "search", Event.key != "")
                .group_by(Event.key)
            )
        ).all()
        active_by_cat = dict(
            (
                await session.execute(
                    select(Specialist.category, func.count())
                    .where(Specialist.status == "active")
                    .group_by(Specialist.category)
                )
            ).all()
        )
        gaps = sorted(
            ((k, c) for k, c in search_by_cat if active_by_cat.get(k, 0) == 0),
            key=lambda x: -x[1],
        )[:10]
        subs = (
            await session.execute(
                select(Submission.type, func.count()).group_by(Submission.type)
            )
        ).all()
        # Искали направления, которых НЕТ в нашем списке категорий (спрос «мимо»)
        misses = (
            await session.execute(
                select(Event.key, func.count())
                .where(Event.type == "search_miss", Event.key != "")
                .group_by(Event.key)
                .order_by(func.count().desc())
                .limit(10)
            )
        ).all()

    lines = [
        "📊 <b>Статистика бота</b>",
        "",
        f"👥 Пользователей: <b>{users}</b> (активных: {active_users})",
        f"🔍 Поисков специалистов: <b>{searches}</b> (вне категорий: {search_miss_total})",
        f"📇 Специалистов в гайде: <b>{specs_active}</b> (платных: {specs_paid})",
        f"⭐ Отзывов: <b>{reviews}</b>",
        f"💳 Успешных оплат: <b>{payments}</b>",
        "",
        "<b>Использование функций:</b>",
        f"💬 Вопросов боту (ИИ): <b>{ai_chats}</b>",
        f"📩 Разборов писем: <b>{letters}</b>",
        f"🧮 Калькулятор зарплаты: <b>{salary}</b>",
        f"📚 «Полезное» (открытий): <b>{guides}</b>",
    ]
    if top_guides:
        lines.append("\n<b>Топ тем «Полезного»:</b>")
        lines += [f"  • {k}: {c}" for k, c in top_guides]
    if top_cats:
        lines.append("\n<b>Топ категорий поиска:</b>")
        lines += [f"  • {k}: {c}" for k, c in top_cats]
    if gaps:
        lines.append("\n<b>🕳 Ищут, но нет в гайде:</b>")
        lines += [f"  • {k}: {c} запр." for k, c in gaps]
        lines.append("<i>↑ сюда стоит позвать специалистов</i>")
    if misses:
        lines.append("\n<b>🔎 Искали, но направления нет в списке:</b>")
        lines += [f"  • {k}: {c}" for k, c in misses]
        lines.append("<i>↑ спрос есть, а категории у нас нет — стоит завести</i>")
    if subs:
        lines.append("\n<b>Заявки:</b>")
        lines += [f"  • {_SUB_TITLES.get(t, t)}: {c}" for t, c in subs]
    return "\n".join(lines)
