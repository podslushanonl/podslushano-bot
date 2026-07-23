"""Центр добровольных персональных уведомлений."""
import asyncio
import html
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import or_, select

from database.db import get_session
from database.models import (
    AlloBooking,
    BotUser,
    DigestPreference,
    DiscoveredEvent,
    EventListing,
    Listing,
    NotificationDelivery,
    NotificationPreference,
    NotificationState,
    SavedItem,
    Specialist,
    Submission,
)
from utils.analytics import log_product_event

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
STATUS_LABELS = {
    "pending": "на проверке",
    "approved": "опубликовано",
    "active": "активна",
    "awaiting_payment": "ждёт оплаты",
    "paid": "оплачено",
    "refund_requested": "возврат запрошен",
    "refunded": "возвращено",
    "rejected": "отклонено",
    "expired": "срок истёк",
    "closed": "закрыто",
    "canceled": "отменено",
}
ENTITY_LABELS = {
    "listing": "Объявление",
    "walk": "Allo Walks",
    "event_listing": "Мероприятие",
    "specialist": "Карточка специалиста",
    "submission": "Заявка",
}


@dataclass(frozen=True)
class PendingNotification:
    key: str
    kind: str
    line: str
    state_update: tuple[str, int, str] | None = None


async def _get_or_create_pref(user_id: int) -> NotificationPreference:
    async with get_session() as session:
        pref = await session.get(NotificationPreference, user_id)
        if pref is None:
            pref = NotificationPreference(user_id=user_id)
            session.add(pref)
            await session.commit()
        return pref


def _settings_text(pref: NotificationPreference) -> str:
    enabled = sum((
        pref.event_reminders,
        pref.new_listings,
        pref.action_updates,
    ))
    frequency = "раз в день" if pref.frequency == "daily" else "раз в неделю"
    state = "включены" if enabled else "выключены"
    return (
        "🔔 <b>Центр уведомлений</b>\n\n"
        f"Сейчас уведомления <b>{state}</b>. Выбери, что действительно важно:\n\n"
        f"{'✅' if pref.event_reminders else '▫️'} Напоминания о сохранённых событиях\n"
        f"{'✅' if pref.new_listings else '▫️'} Новые объявления рядом\n"
        f"{'✅' if pref.action_updates else '▫️'} Изменения статусов моих действий\n\n"
        f"⏱ Общая частота: <b>{frequency}</b>\n\n"
        "События — исключение: если напоминание включено, оно приходит накануне. "
        "Четверговая подборка настраивается отдельно."
    )


def _settings_kb(pref: NotificationPreference) -> InlineKeyboardMarkup:
    def mark(value: bool) -> str:
        return "✅" if value else "▫️"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{mark(pref.event_reminders)} Сохранённые события",
            callback_data="nt:toggle:event",
        )],
        [InlineKeyboardButton(
            text=f"{mark(pref.new_listings)} Новые объявления",
            callback_data="nt:toggle:listings",
        )],
        [InlineKeyboardButton(
            text=f"{mark(pref.action_updates)} Статусы действий",
            callback_data="nt:toggle:actions",
        )],
        [
            InlineKeyboardButton(
                text=("● Ежедневно" if pref.frequency == "daily" else "○ Ежедневно"),
                callback_data="nt:frequency:daily",
            ),
            InlineKeyboardButton(
                text=("● Еженедельно" if pref.frequency == "weekly" else "○ Еженедельно"),
                callback_data="nt:frequency:weekly",
            ),
        ],
        [InlineKeyboardButton(text="☀️ Подборка по четвергам", callback_data="home:digest")],
        [InlineKeyboardButton(text="⬅️ Мой Podslushano", callback_data="home:open")],
    ])


async def _open_settings(message: Message, user_id: int, *, source: str) -> None:
    pref = await _get_or_create_pref(user_id)
    await message.answer(_settings_text(pref), reply_markup=_settings_kb(pref))
    await log_product_event(user_id, "notifications_open", source=source)


@router.message(Command("notifications"))
async def notifications_command(message: Message) -> None:
    await _open_settings(message, message.from_user.id, source="command")


@router.callback_query(F.data == "home:notifications")
async def notifications_from_home(callback: CallbackQuery) -> None:
    await callback.answer()
    await _open_settings(callback.message, callback.from_user.id, source="home")


@router.callback_query(F.data.startswith("nt:toggle:"))
async def notification_toggle(callback: CallbackQuery) -> None:
    key = callback.data.rsplit(":", 1)[1]
    fields = {
        "event": "event_reminders",
        "listings": "new_listings",
        "actions": "action_updates",
    }
    field = fields.get(key)
    if field is None:
        await callback.answer("Неизвестная настройка", show_alert=True)
        return
    async with get_session() as session:
        pref = await session.get(NotificationPreference, callback.from_user.id)
        if pref is None:
            pref = NotificationPreference(user_id=callback.from_user.id)
            session.add(pref)
        enabled = not bool(getattr(pref, field))
        setattr(pref, field, enabled)
        await session.commit()
    if key == "actions" and enabled:
        await _sync_action_states(callback.from_user.id)
    updated = await _get_or_create_pref(callback.from_user.id)
    await callback.message.edit_text(
        _settings_text(updated), reply_markup=_settings_kb(updated)
    )
    await log_product_event(
        callback.from_user.id,
        "notification_enabled" if enabled else "notification_disabled",
        entity_type=key,
    )
    await callback.answer("Включено" if enabled else "Выключено")


@router.callback_query(F.data.startswith("nt:frequency:"))
async def notification_frequency(callback: CallbackQuery) -> None:
    frequency = callback.data.rsplit(":", 1)[1]
    if frequency not in {"daily", "weekly"}:
        await callback.answer("Неизвестная частота", show_alert=True)
        return
    async with get_session() as session:
        pref = await session.get(NotificationPreference, callback.from_user.id)
        if pref is None:
            pref = NotificationPreference(user_id=callback.from_user.id)
            session.add(pref)
        pref.frequency = frequency
        await session.commit()
    updated = await _get_or_create_pref(callback.from_user.id)
    await callback.message.edit_text(
        _settings_text(updated), reply_markup=_settings_kb(updated)
    )
    await log_product_event(
        callback.from_user.id,
        "notification_frequency",
        entity_type=frequency,
    )
    await callback.answer("Частота обновлена")


async def _action_rows(user_id: int) -> list[tuple[str, int, str, str]]:
    """Возвращает тип, id, статус и понятное название собственных действий."""
    async with get_session() as session:
        listings = (await session.scalars(
            select(Listing).where(Listing.submitter_user_id == user_id)
        )).all()
        walks = (await session.scalars(
            select(AlloBooking).where(AlloBooking.user_id == user_id)
        )).all()
        events = (await session.scalars(
            select(EventListing).where(EventListing.submitter_user_id == user_id)
        )).all()
        specialists = (await session.scalars(
            select(Specialist).where(Specialist.submitter_user_id == user_id)
        )).all()
        submissions = (await session.scalars(
            select(Submission).where(Submission.user_id == user_id)
        )).all()
    return (
        [("listing", x.id, x.status, x.title) for x in listings]
        + [("walk", x.id, x.status, x.walk_key) for x in walks]
        + [("event_listing", x.id, x.status, x.title) for x in events]
        + [("specialist", x.id, x.status, x.name) for x in specialists]
        + [("submission", x.id, x.status, x.type) for x in submissions]
    )


async def _sync_action_states(user_id: int) -> None:
    """Создаёт стартовый снимок без отправки старых статусов."""
    rows = await _action_rows(user_id)
    async with get_session() as session:
        for entity_type, entity_id, status, _ in rows:
            existing = (await session.scalars(select(NotificationState).where(
                NotificationState.user_id == user_id,
                NotificationState.entity_type == entity_type,
                NotificationState.entity_id == entity_id,
            ))).first()
            if existing is None:
                session.add(NotificationState(
                    user_id=user_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    last_status=status,
                ))
        await session.commit()


async def _action_changes(user_id: int) -> list[PendingNotification]:
    rows = await _action_rows(user_id)
    changes: list[PendingNotification] = []
    async with get_session() as session:
        for entity_type, entity_id, status, title in rows:
            state = (await session.scalars(select(NotificationState).where(
                NotificationState.user_id == user_id,
                NotificationState.entity_type == entity_type,
                NotificationState.entity_id == entity_id,
            ))).first()
            if state is None:
                session.add(NotificationState(
                    user_id=user_id, entity_type=entity_type,
                    entity_id=entity_id, last_status=status,
                ))
                continue
            if state.last_status == status:
                continue
            changes.append(PendingNotification(
                key=f"status:{entity_type}:{entity_id}:{status}",
                kind="action_status",
                line=(
                    f"🗂 {ENTITY_LABELS.get(entity_type, 'Действие')} "
                    f"«{html.escape(title)}»: "
                    f"<b>{html.escape(STATUS_LABELS.get(status, status))}</b>"
                ),
                state_update=(entity_type, entity_id, status),
            ))
        await session.commit()
    return changes


async def _already_sent(user_id: int, key: str) -> bool:
    async with get_session() as session:
        return bool((await session.scalars(select(NotificationDelivery).where(
            NotificationDelivery.user_id == user_id,
            NotificationDelivery.delivery_key == key,
            NotificationDelivery.status == "sent",
        ))).first())


async def _event_reminders(
    user_id: int, tomorrow: date
) -> list[PendingNotification]:
    from handlers.digest import _listing_event_day

    async with get_session() as session:
        saved = (await session.scalars(select(SavedItem).where(
            SavedItem.user_id == user_id,
            SavedItem.item_type.in_(("event", "discovered_event")),
        ))).all()
        manual_ids = [x.item_id for x in saved if x.item_type == "event"]
        discovered_ids = [
            x.item_id for x in saved if x.item_type == "discovered_event"
        ]
        manual = {
            x.id: x for x in (await session.scalars(select(EventListing).where(
                EventListing.id.in_(manual_ids or [-1]),
                EventListing.status == "approved",
            ))).all()
        }
        discovered = {
            x.id: x for x in (await session.scalars(select(DiscoveredEvent).where(
                DiscoveredEvent.id.in_(discovered_ids or [-1])
            ))).all()
        }
    result: list[PendingNotification] = []
    for row in saved:
        if row.item_type == "event":
            item = manual.get(row.item_id)
            day = _listing_event_day(item.event_date, today=tomorrow) if item else None
        else:
            item = discovered.get(row.item_id)
            day = item.starts_at.date() if item and item.starts_at else None
        if item is None or day != tomorrow:
            continue
        key = f"event:{row.item_type}:{row.item_id}:{tomorrow.isoformat()}"
        if await _already_sent(user_id, key):
            continue
        city = getattr(item, "city", "") or "Нидерланды"
        result.append(PendingNotification(
            key=key,
            kind="event_reminder",
            line=(
                f"📅 Завтра: <b>{html.escape(item.title)}</b>"
                f" · {html.escape(city)}"
            ),
        ))
    return result


async def _new_listing_notifications(
    user_id: int,
    pref: DigestPreference | None,
    *,
    since: datetime,
) -> list[PendingNotification]:
    from handlers.digest import location_matches

    if pref is None:
        return []
    current = datetime.now()
    async with get_session() as session:
        rows = (await session.scalars(select(Listing).where(
            Listing.status == "approved",
            Listing.created_at >= since,
            or_(Listing.expires_at.is_(None), Listing.expires_at > current),
        ).order_by(Listing.created_at.desc()).limit(30))).all()
    result: list[PendingNotification] = []
    for item in rows:
        if not location_matches(pref, item.city, nationwide=item.is_nationwide):
            continue
        key = f"listing:{item.id}"
        if await _already_sent(user_id, key):
            continue
        result.append(PendingNotification(
            key=key,
            kind="new_listing",
            line=f"🆕 <b>{html.escape(item.title)}</b> · {html.escape(item.city or 'Нидерланды')}",
        ))
    return result[:8]


async def _record_success(
    user_id: int,
    items: list[PendingNotification],
    message_id: int | None,
) -> None:
    async with get_session() as session:
        for item in items:
            existing = (await session.scalars(select(NotificationDelivery).where(
                NotificationDelivery.user_id == user_id,
                NotificationDelivery.delivery_key == item.key,
            ))).first()
            if existing:
                existing.status = "sent"
                existing.telegram_message_id = message_id
                existing.error_text = None
            else:
                session.add(NotificationDelivery(
                    user_id=user_id,
                    delivery_key=item.key,
                    kind=item.kind,
                    status="sent",
                    telegram_message_id=message_id,
                ))
            if item.state_update:
                entity_type, entity_id, status = item.state_update
                state = (await session.scalars(select(NotificationState).where(
                    NotificationState.user_id == user_id,
                    NotificationState.entity_type == entity_type,
                    NotificationState.entity_id == entity_id,
                ))).first()
                if state:
                    state.last_status = status
        await session.commit()


async def run_notification_cycle(bot, *, now: datetime | None = None) -> tuple[int, int]:
    """Собирает и отправляет персональные пакеты; безопасно повторяется."""
    current = now or datetime.now(AMSTERDAM)
    if current.tzinfo is None:
        current = current.replace(tzinfo=AMSTERDAM)
    local_naive = current.replace(tzinfo=None)
    tomorrow = current.date() + timedelta(days=1)
    sent = failed = 0
    async with get_session() as session:
        prefs = (await session.scalars(select(NotificationPreference).where(or_(
            NotificationPreference.event_reminders.is_(True),
            NotificationPreference.new_listings.is_(True),
            NotificationPreference.action_updates.is_(True),
        )))).all()

    for notification_pref in prefs:
        user_id = notification_pref.user_id
        async with get_session() as session:
            profile = await session.get(DigestPreference, user_id)
        items: list[PendingNotification] = []
        if notification_pref.event_reminders:
            items += await _event_reminders(user_id, tomorrow)
        scheduled = (
            notification_pref.frequency == "daily"
            or (
                notification_pref.frequency == "weekly"
                and current.weekday() == 3
            )
        )
        if scheduled and notification_pref.new_listings:
            days = 1 if notification_pref.frequency == "daily" else 7
            items += await _new_listing_notifications(
                user_id, profile, since=local_naive - timedelta(days=days)
            )
        if scheduled and notification_pref.action_updates:
            items += await _action_changes(user_id)
        if not items:
            continue
        text = (
            "🔔 <b>Для тебя есть обновления</b>\n\n"
            + "\n".join(item.line for item in items)
            + "\n\n<i>Настройки — /notifications</i>"
        )
        try:
            message = await bot.send_message(
                user_id, text, disable_web_page_preview=True
            )
            await _record_success(
                user_id, items, getattr(message, "message_id", None)
            )
            await log_product_event(
                user_id, "notification_sent",
                entity_type="batch", entity_id=len(items),
            )
            sent += 1
        except TelegramForbiddenError:
            async with get_session() as session:
                user = await session.get(BotUser, user_id)
                if user:
                    user.is_blocked = True
                    await session.commit()
            failed += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось отправить уведомления %s: %s", user_id, exc)
            failed += 1
        await asyncio.sleep(0.04)
    return sent, failed


async def notification_loop(bot) -> None:
    """Ежечасно проверяет, наступило ли 10:00 по Амстердаму."""
    while True:
        try:
            now = datetime.now(AMSTERDAM)
            if now.hour == 10:
                await run_notification_cycle(bot, now=now)
        except Exception as exc:  # noqa: BLE001
            log.warning("Ошибка цикла персональных уведомлений: %s", exc)
        await asyncio.sleep(3600)
