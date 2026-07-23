"""Простая аналитика: лог событий и сводка для админа."""
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from database.db import get_session
from database.models import (
    BotUser,
    Event,
    ProductEvent,
    Review,
    Specialist,
    Submission,
)

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


async def log_product_event(
    user_id: int,
    name: str,
    *,
    entity_type: str = "",
    entity_id: int | None = None,
    source: str = "",
) -> None:
    """Записывает действие без содержимого сообщений и контактных данных."""
    try:
        async with get_session() as session:
            session.add(ProductEvent(
                user_id=user_id,
                name=name[:50],
                entity_type=entity_type[:30],
                entity_id=entity_id,
                source=source[:30],
            ))
            await session.commit()
    except Exception as e:  # noqa: BLE001 — аналитика не должна ломать сценарий
        log.warning("Не удалось записать продуктовое событие %s: %s", name, e)


_PRODUCT_LABELS = {
    "home_open": "Открыли «Мой Podslushano»",
    "profile_open": "Открыли настройки профиля",
    "profile_completed": "Заполнили профиль",
    "profile_updated": "Изменили профиль",
    "digest_open": "Открыли настройки подборки",
    "digest_enabled": "Включили подборку",
    "digest_disabled": "Отключили подборку",
    "saved_open": "Открыли сохранённое",
    "saved_add": "Сохранили карточку",
    "saved_remove": "Удалили из сохранённого",
    "actions_open": "Открыли «Мои действия»",
    "home_events_open": "Открыли события с персональной главной",
    "home_new_listings_open": "Открыли новые объявления с персональной главной",
    "specialist_open": "Открыли специалиста",
    "listing_open": "Открыли объявление",
    "submission_created": "Отправили заявку",
}


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


async def gather_product_stats(now: datetime | None = None) -> str:
    """Сводка продуктовой активности, воронки и D1/D7/D30 retention."""
    current = now or datetime.utcnow()
    today = current.date()
    cutoff_7 = current - timedelta(days=7)
    cutoff_30 = current - timedelta(days=30)

    async with get_session() as session:
        recent = (await session.execute(
            select(ProductEvent.name, ProductEvent.user_id, ProductEvent.created_at)
            .where(ProductEvent.created_at >= cutoff_30)
        )).all()
        activity_days = (await session.execute(
            select(
                ProductEvent.user_id,
                func.date(ProductEvent.created_at),
            ).distinct()
        )).all()

    by_name_7: dict[str, set[int]] = defaultdict(set)
    by_name_30: dict[str, set[int]] = defaultdict(set)
    active_1: set[int] = set()
    active_7: set[int] = set()
    active_30: set[int] = set()
    cutoff_1 = current - timedelta(days=1)
    for name, user_id, created_at in recent:
        active_30.add(user_id)
        by_name_30[name].add(user_id)
        if created_at >= cutoff_7:
            active_7.add(user_id)
            by_name_7[name].add(user_id)
        if created_at >= cutoff_1:
            active_1.add(user_id)

    days_by_user: dict[int, set[date]] = defaultdict(set)
    for user_id, day in activity_days:
        days_by_user[user_id].add(_as_date(day))

    def retention(day_number: int) -> tuple[int, int]:
        eligible = returned = 0
        for days in days_by_user.values():
            first = min(days)
            target = first + timedelta(days=day_number)
            if target <= today:
                eligible += 1
                returned += target in days
        return returned, eligible

    def pct(value: tuple[int, int]) -> str:
        returned, eligible = value
        if not eligible:
            return "—"
        return f"{returned}/{eligible} ({returned / eligible:.0%})"

    funnel = (
        ("home_open", "открыли"),
        ("profile_completed", "заполнили профиль"),
        ("saved_add", "сохранили"),
        ("specialist_open", "открыли специалиста"),
        ("submission_created", "отправили заявку"),
    )
    lines = [
        "📈 <b>Продуктовая аналитика</b>",
        "",
        "<b>Уникальные пользователи:</b>",
        f"• за 24 часа: <b>{len(active_1)}</b>",
        f"• за 7 дней: <b>{len(active_7)}</b>",
        f"• за 30 дней: <b>{len(active_30)}</b>",
        "",
        "<b>Возвращение от первого действия:</b>",
        f"• D1: <b>{pct(retention(1))}</b>",
        f"• D7: <b>{pct(retention(7))}</b>",
        f"• D30: <b>{pct(retention(30))}</b>",
        "",
        "<b>Воронка за 30 дней:</b>",
    ]
    lines.extend(
        f"• {label}: <b>{len(by_name_30[name])}</b>"
        for name, label in funnel
    )
    used = [
        (name, len(users))
        for name, users in by_name_7.items()
        if users and name in _PRODUCT_LABELS
    ]
    if used:
        lines += ["", "<b>Действия за 7 дней:</b>"]
        lines.extend(
            f"• {_PRODUCT_LABELS[name]}: <b>{count}</b>"
            for name, count in sorted(used, key=lambda item: (-item[1], item[0]))
        )
    lines += [
        "",
        "<i>Счётчики начнут заполняться после выхода этого релиза. "
        "D7 и D30 появятся, когда пройдёт достаточно времени.</i>",
    ]
    return "\n".join(lines)


async def gather_stats() -> str:
    """Собирает текстовую сводку статистики."""
    async with get_session() as session:
        users = await session.scalar(select(func.count()).select_from(BotUser)) or 0
        active_users = await session.scalar(
            select(func.count()).select_from(BotUser).where(BotUser.is_blocked.is_(False))
        ) or 0
        blocked_users = await session.scalar(
            select(func.count()).select_from(BotUser).where(BotUser.is_blocked.is_(True))
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
        f"👥 Пользователей: <b>{users}</b> (активных: {active_users}, "
        f"🚫 заблокировали бота: {blocked_users})",
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
