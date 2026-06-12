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
from datetime import date

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
    "• ВСЯ информация должна быть актуальной. Конкретные цифры — ставки налогов, "
    "суммы пособий (toeslagen), пошлины, лимиты, сроки, правила — в Нидерландах "
    "часто меняются (обычно раз в год). Если не уверен в актуальном на СЕГОДНЯ "
    "значении — НЕ называй устаревшие числа как текущие.\n"
    "• У тебя есть ВЕБ-ПОИСК. Используй его сам, когда нужна свежая или точная "
    "информация: актуальные суммы и ставки, пошлины, сроки, изменения правил, "
    "новости, расписания, текущие события. Не выдумывай — лучше найди. Для "
    "официальных тем (налоги, BSN, DigiD, визы и ВНЖ через IND, пособия) ищи в "
    "первую очередь на официальных нидерландских сайтах: belastingdienst.nl, "
    "toeslagen.nl, ind.nl, digid.nl, government.nl, rijksoverheid.nl и сайте "
    "нужного gemeente. Ссылки на источники подставятся автоматически — тебе их "
    "вписывать не нужно, просто давай точный ответ на основе найденного.\n"
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


def _web_search_tool() -> list | None:
    """Инструмент веб-поиска (если включён) — даёт ИИ доступ к свежим данным."""
    if not config.AI_WEB_SEARCH:
        return None
    return [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": config.AI_WEB_MAX_USES,
            # Подсказываем местоположение — результаты релевантнее для NL
            "user_location": {
                "type": "approximate",
                "country": "NL",
                "timezone": "Europe/Amsterdam",
            },
        }
    ]


def _extract_text_and_sources(response) -> tuple[str, list[str]]:
    """Собирает финальный текст ответа и реальные ссылки из веб-поиска.

    Когда модель искала в интернете, её текстовые блоки содержат цитаты с url —
    их и берём, чтобы честно показать источники под ответом.
    """
    text_parts: list[str] = []
    sources: list[str] = []
    seen: set[str] = set()
    for block in response.content:
        if getattr(block, "type", None) != "text":
            continue
        text_parts.append(block.text)
        for cit in getattr(block, "citations", None) or []:
            url = getattr(cit, "url", None) if not isinstance(cit, dict) else cit.get("url")
            if url and url not in seen:
                seen.add(url)
                sources.append(url)
    return "".join(text_parts).strip(), sources


async def ai_reply(
    user_text: str, history: list[dict] | None = None
) -> str | None:
    """Возвращает ответ ИИ на сообщение пользователя.

    history — список вида [{"role": "user"/"assistant", "content": "..."}],
    последние реплики диалога для связного контекста.

    Если включён веб-поиск, модель сама решает, когда искать в интернете
    свежие данные. Веб-поиск «лучшее усилие»: если он недоступен — пробуем
    ответить без него. При любой ошибке или без ключа возвращаем None.
    """
    if not ai_enabled():
        return None

    messages = list(history or [])
    messages.append({"role": "user", "content": user_text})

    today = date.today().strftime("%d.%m.%Y")
    system = (
        f"{SYSTEM_PROMPT}\n\nСегодняшняя дата: {today}. Отвечай так, будто это "
        "и есть текущий момент; не выдавай устаревшие данные за сегодняшние."
    )

    client = _get_client()

    async def _create(tools):
        kwargs = dict(
            model=config.AI_MODEL,
            max_tokens=900,
            system=system,
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools
        return await client.messages.create(**kwargs)

    try:
        response = await _create(_web_search_tool())
    except Exception as e:  # noqa: BLE001 — веб-поиск не сработал, пробуем без него
        log.warning("ИИ с веб-поиском не сработал (%s) — пробую без поиска", e)
        try:
            response = await _create(None)
        except Exception as e2:  # noqa: BLE001 — никогда не роняем бота из-за ИИ
            log.warning("Ошибка обращения к ИИ: %s", e2)
            return None

    return _finalize(response)


def _finalize(response) -> str | None:
    """Готовит итоговый текст: чистим markdown и добавляем источники веб-поиска."""
    text, sources = _extract_text_and_sources(response)
    text = _clean(text)
    if not text:
        return None
    if sources:
        footer = "\n\n🔗 Источник: " + ", ".join(sources[:3])
        text = f"{text}{footer}"
    return text


def _clean(text: str) -> str:
    """Убирает остатки markdown-разметки: мы шлём чистый текст, без HTML/MD.

    Модель изредка ставит **жирный** или __подчёркнутый__ — в чистом тексте
    это выглядит как лишние звёздочки, поэтому маркеры просто срезаем.
    """
    return text.replace("**", "").replace("__", "")


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
