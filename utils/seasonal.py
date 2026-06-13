"""Сезонные напоминания о реальных дедлайнах в Нидерландах.

Бот сам пишет всем пользователям в нужные дни (раз в год): смена медстраховки,
открытие и дедлайн налоговой декларации. Только настоящие даты, тёплый тон,
официальные ссылки. Отправляется один раз на каждое событие в году
(защита от повторов через таблицу Meta).

Чтобы изменить даты/тексты — правь SEASONAL ниже. Чтобы добавить событие —
добавь новый словарь с ключом, датами-триггерами и текстом.
"""
import asyncio
import logging
from datetime import date, timedelta

from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select

from database.db import get_session
from database.models import BotUser, Meta

log = logging.getLogger(__name__)

# triggers — даты (месяц, день), когда отправляем. Обычно «предупреждение заранее»
# + «последний звонок» накануне дедлайна.
SEASONAL = [
    {
        "key": "zorg_switch",
        "triggers": [(12, 13), (12, 28)],
        "text": (
            "🩺 <b>Напоминание: до 31 декабря можно сменить медстраховку</b>\n\n"
            "Раз в год можно перейти на другую <b>zorgverzekering</b> на следующий год — "
            "иногда это экономит сотни евро. Старую страховку нужно отменить до 31 декабря, "
            "а новую оформить до 31 января.\n\n"
            "Сравнить условия: independer.nl или zorgwijzer.nl 👍\n\n"
            "💬 Не уверены, что выбрать? Спросите меня."
        ),
    },
    {
        "key": "tax_open",
        "triggers": [(3, 1)],
        "text": (
            "📄 <b>Открылась подача налоговой декларации</b>\n\n"
            "С 1 марта можно подать декларацию о доходах (<b>aangifte inkomstenbelasting</b>) "
            "за прошлый год — на сайте Belastingdienst, вход по DigiD. Многим возвращают "
            "часть уплаченного налога 💶\n\n"
            "Подробнее: belastingdienst.nl\n\n"
            "💬 Нужен бухгалтер? Нажмите «🔍 Найти специалиста»."
        ),
    },
    {
        "key": "tax_deadline",
        "triggers": [(4, 23), (4, 30)],
        "text": (
            "⏰ <b>Скоро дедлайн налоговой декларации — 1 мая</b>\n\n"
            "Если ещё не подали <b>aangifte</b> за прошлый год — успейте до 1 мая "
            "(подавшим вовремя ответят до 1 июля). Нужно больше времени? Можно запросить "
            "отсрочку (uitstel) на belastingdienst.nl.\n\n"
            "💬 Запутались — спросите меня."
        ),
    },
]


async def check_seasonal(bot) -> None:
    """Проверяет, не наступила ли дата какого-то напоминания, и рассылает один раз."""
    today = date.today()
    for ev in SEASONAL:
        for month, day in ev["triggers"]:
            try:
                trigger = date(today.year, month, day)
            except ValueError:
                continue
            # окно 2 дня — на случай, если бот был офлайн в сам день триггера
            if not (trigger <= today <= trigger + timedelta(days=1)):
                continue
            flag = f"seasonal:{ev['key']}:{month:02d}{day:02d}:{today.year}"
            async with get_session() as session:
                if await session.get(Meta, flag):
                    continue  # это напоминание в этом году уже отправлено
                session.add(Meta(key=flag, value="sent"))
                await session.commit()
            log.info("Сезонное напоминание: рассылаю %s", flag)
            await _broadcast(bot, ev["text"])


async def _broadcast(bot, text: str) -> None:
    async with get_session() as session:
        user_ids = (
            await session.scalars(select(BotUser.user_id).where(BotUser.is_blocked.is_(False)))
        ).all()
    for uid in user_ids:
        try:
            await bot.send_message(uid, text, disable_web_page_preview=True)
        except TelegramForbiddenError:
            async with get_session() as session:
                u = await session.get(BotUser, uid)
                if u:
                    u.is_blocked = True
                    await session.commit()
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(0.05)  # ~20 сообщений/сек — в пределах лимитов Telegram
