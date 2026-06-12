"""«Мозг» бота на основе модели Claude.

Бот отвечает на свободные сообщения как живой умный собеседник: помогает
с бытовыми вопросами о жизни в Нидерландах, поддерживает разговор, при этом
НЕ выдумывает контакты специалистов (для этого есть поиск по базе) и не даёт
юридических/медицинских гарантий.

Если ключ ANTHROPIC_API_KEY не задан или произошла ошибка — функции вернут
None, и вызывающий код мягко откатится на правила. Бот не упадёт.
"""
from __future__ import annotations

import logging

import config

log = logging.getLogger(__name__)

# Клиент создаётся один раз (лениво), чтобы не дёргать сеть при импорте.
_client = None

# Сколько последних реплик помним в диалоге (пар «пользователь — бот»).
HISTORY_LIMIT = 8

SYSTEM_PROMPT = (
    "Ты — дружелюбный и умный ассистент Telegram-бота сообщества "
    "«Подслушано в Нидерландах». Сообщество объединяет русскоязычных людей, "
    "которые живут в Нидерландах (NL). Твоя задача — помогать им и приятно "
    "общаться.\n\n"
    "Как ты общаешься:\n"
    "• По-русски, тепло, с лёгким юмором, но уважительно и по делу.\n"
    "• Коротко — это мессенджер. Обычно 2–5 предложений. Не лей воду.\n"
    "• Изредка уместный эмодзи (1–2 на сообщение), не перебарщивай.\n"
    "• Пиши живым человеческим языком, без канцелярита и шаблонов.\n\n"
    "В чём помогаешь: быт и адаптация в Нидерландах — BSN и DigiD, регистрация "
    "в gemeente, жильё и huurtoeslag, налоги (belastingdienst), медицина "
    "(huisarts, zorgverzekering), транспорт (OV-chip), банки, школы/детсады, "
    "работа, язык, культурные нюансы. Давай практичные, конкретные советы.\n\n"
    "Важные правила:\n"
    "• Ты НЕ придумываешь имена, телефоны и контакты специалистов. Если человеку "
    "нужен конкретный специалист (стоматолог, юрист, парикмахер и т.п.), скажи, "
    "что у бота есть поиск по проверенному гайду — пусть нажмёт «🔍 Найти "
    "специалиста» или напишет, например, «нужен стоматолог в Амстердаме».\n"
    "• По юридическим, налоговым и медицинским вопросам давай общую ориентировку, "
    "но советуй сверяться с официальными источниками (gemeente, belastingdienst, "
    "huisarts), не выдавай это за точную консультацию.\n"
    "• Если вопрос личный/основан на опыте (отзывы, «как лучше», «куда сходить»), "
    "можешь предложить отправить его в предложку сообщества — там ответят живые "
    "люди.\n"
    "• Не используй HTML или Markdown-разметку — только обычный текст и эмодзи.\n"
    "• Если не знаешь — честно скажи об этом, не выдумывай факты."
)


def ai_enabled() -> bool:
    """ИИ доступен, если задан ключ."""
    return bool(config.ANTHROPIC_API_KEY)


def _get_client():
    """Лениво создаёт асинхронного клиента Anthropic."""
    global _client
    if _client is None:
        from anthropic import AsyncAnthropic

        _client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


async def ai_reply(
    user_text: str, history: list[dict] | None = None
) -> str | None:
    """Возвращает ответ ИИ на сообщение пользователя.

    history — список вида [{"role": "user"/"assistant", "content": "..."}],
    последние реплики диалога для связного контекста.

    При любой ошибке или без ключа возвращает None (вызывающий код откатится).
    """
    if not ai_enabled():
        return None

    messages = list(history or [])
    messages.append({"role": "user", "content": user_text})

    try:
        client = _get_client()
        response = await client.messages.create(
            model=config.AI_MODEL,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        parts = [block.text for block in response.content if block.type == "text"]
        text = "".join(parts).strip()
        return text or None
    except Exception as e:  # noqa: BLE001 — никогда не роняем бота из-за ИИ
        log.warning("Ошибка обращения к ИИ: %s", e)
        return None


async def reply_with_ai(message, state) -> bool:
    """Отвечает на свободное сообщение через ИИ и помнит контекст диалога.

    Возвращает True, если ИИ ответил (тогда вызывающему коду делать ничего не
    нужно), и False — если ИИ выключен или не смог ответить (нужен запасной
    вариант). Заодно выходит из любого «залипшего» режима (clear) — кроме
    истории диалога, которую сохраняем.
    """
    if not ai_enabled():
        return False

    from keyboards.menus import main_menu

    user_text = (message.text or "").strip()
    if not user_text:
        return False

    await message.bot.send_chat_action(message.chat.id, action="typing")
    data = await state.get_data()
    history = data.get("ai_history", [])
    reply = await ai_reply(user_text, history)
    if not reply:
        return False

    history = (
        history
        + [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": reply},
        ]
    )[-2 * HISTORY_LIMIT:]
    await state.clear()
    await state.update_data(ai_history=history)
    await message.answer(reply, reply_markup=main_menu(), parse_mode=None)
    return True
