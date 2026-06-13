"""«Мозг» бота на основе модели Claude.

Бот отвечает на свободные сообщения как живой умный собеседник: помогает
с бытовыми вопросами о жизни в Нидерландах, поддерживает разговор, при этом
НЕ выдумывает контакты специалистов (для этого есть поиск по базе) и не даёт
юридических/медицинских гарантий.

Если ключ ANTHROPIC_API_KEY не задан или произошла ошибка — функции вернут
None, и вызывающий код мягко откатится на правила. Бот не упадёт.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from urllib.parse import urlparse

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
    "новости, расписания, текущие события. Не выдумывай — лучше найди.\n"
    "• ОФИЦИАЛЬНЫЕ ТЕМЫ (документы, налоги, пособия/toeslagen, BSN, DigiD, визы и "
    "ВНЖ через IND, штрафы, пошлины, регистрация, права/CBR/RDW, страховки, "
    "пенсии/SVB, UWV): опирайся и ссылайся ТОЛЬКО на официальные нидерландские "
    "сайты — belastingdienst.nl, toeslagen.nl, ind.nl, digid.nl, government.nl, "
    "rijksoverheid.nl, overheid.nl, cbr.nl, rdw.nl, duo.nl, uwv.nl, svb.nl, kvk.nl "
    "и сайт нужного gemeente. НЕ бери факты по таким темам с форумов, блогов, "
    "частных и коммерческих сайтов, агрегаторов — там бывает устаревшее и неверное. "
    "Если на официальном сайте точного ответа не нашёл — так и скажи и подскажи, "
    "где именно на официальном сайте это посмотреть, а не подставляй неофициальный "
    "источник. Ссылки подставятся автоматически — просто дай точный ответ.\n"
    "• Для бытовых/опытных тем (куда сходить, отзывы, лайфхаки) можно искать "
    "и в обычных источниках.\n"
    "• Если вопрос личный/основан на опыте (отзывы, «как лучше», «куда сходить»), "
    "можешь предложить отправить его в предложку сообщества — там ответят живые "
    "люди.\n"
    "• НЕ описывай процесс поиска. Не пиши «сейчас поищу», «давай посмотрю», "
    "«я нашёл информацию» и т.п. — сразу давай готовый ответ. Ссылка на источник "
    "подставится автоматически в конце.\n"
    "• Если человек хочет связаться с командой/создателем бота, сообщить о проблеме "
    "или обсудить возврат — направь его нажать кнопку «✉️ Связаться с нами» в меню "
    "или команду /contact (его сообщение придёт нашей команде). Не выдумывай другие "
    "способы связи.\n"
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
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(block.text)
            for cit in getattr(block, "citations", None) or []:
                url = getattr(cit, "url", None) if not isinstance(cit, dict) else cit.get("url")
                if url and url not in seen:
                    seen.add(url)
                    sources.append(url)
        else:
            # Блок поиска/инструмента: всё, что было до него — это «преамбула»
            # модели («сейчас поищу…»). Отбрасываем её, оставляем финальный ответ.
            text_parts.clear()
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


# Официальные нидерландские источники — им отдаём приоритет в ссылке
OFFICIAL_DOMAINS = (
    "belastingdienst.nl", "toeslagen.nl", "ind.nl", "digid.nl",
    "government.nl", "rijksoverheid.nl", "overheid.nl", "mijnoverheid.nl",
    "cbr.nl", "rdw.nl", "duo.nl", "uwv.nl", "svb.nl", "kvk.nl",
    "werk.nl", "business.gov.nl", "rivm.nl", "politie.nl",
    "iamsterdam.com", "denederlandseziekenfonds.nl",
)


def _is_official(url: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if host.endswith(".overheid.nl") or host.endswith(".nl") and "gemeente" in host:
        return True
    return any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


def _pick_source(sources: list[str]) -> str | None:
    """Выбирает ОДИН источник, отдавая приоритет официальным сайтам."""
    if not sources:
        return None
    for url in sources:
        if _is_official(url):
            return url
    return sources[0]


def _finalize(response) -> str | None:
    """Готовит итоговый текст: чистим markdown и добавляем один источник."""
    text, sources = _extract_text_and_sources(response)
    text = _clean(text)
    if not text:
        return None
    source = _pick_source(sources)
    if source:
        text = f"{text}\n\n🔗 Источник: {source}"
    return text


def _clean(text: str) -> str:
    """Убирает остатки markdown-разметки: мы шлём чистый текст, без HTML/MD.

    Модель изредка ставит **жирный** или __подчёркнутый__ — в чистом тексте
    это выглядит как лишние звёздочки, поэтому маркеры просто срезаем.
    """
    return text.replace("**", "").replace("__", "")


def _parse_json(raw: str) -> dict:
    """Достаёт JSON-объект из ответа модели (даже если он обёрнут в текст)."""
    raw = raw.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        return json.loads(raw[start : end + 1])
    except Exception:  # noqa: BLE001
        return {}


async def extract_specialist_query(
    text: str, categories: list[str], provinces: list[str] | None = None
) -> dict:
    """Через ИИ понимает, какого специалиста, в каком городе и провинции ищут.

    Возвращает {"category": <из categories|None>, "city": <город|None>,
    "province": <провинция NL|None>}. Понимает синонимы и опечатки, знает, к какой
    провинции относится даже маленький город. Если это НЕ запрос специалиста —
    category=None. Веб-поиск тут не нужен — быстрая дешёвая классификация.
    """
    empty = {"category": None, "city": None, "province": None}
    if not ai_enabled():
        return dict(empty)

    cats = ", ".join(categories)
    provs = ", ".join(provinces) if provinces else (
        "Groningen, Friesland, Drenthe, Overijssel, Flevoland, Gelderland, "
        "Utrecht, Noord-Holland, Zuid-Holland, Zeeland, Noord-Brabant, Limburg"
    )
    system = (
        "Ты — классификатор запросов для справочника специалистов в Нидерландах. "
        "По сообщению пользователя определи, ищет ли он КОНКРЕТНОГО специалиста или "
        "услугу из списка категорий, и если да — верни категорию, город и "
        "провинцию.\n\n"
        f"Категории: {cats}.\n"
        f"Провинции (12, пиши ровно так): {provs}.\n\n"
        "Правила:\n"
        "- Понимай синонимы и опечатки (зубной→стоматолог, адвокат→юрист, "
        "электрик/сантехник→мастер на час, ноготочки→мастер маникюра).\n"
        "- Если это НЕ поиск специалиста из списка (общий вопрос, совет про "
        "места/кафе/досуг, болтовня) — category=null.\n"
        "- city — город как в сообщении (можно по-русски), иначе null.\n"
        "- province — провинция NL для этого города (ровно из списка). Ты знаешь, "
        "к какой провинции относится даже маленький городок (Oisterwijk→"
        "Noord-Brabant). Если город не назван — null.\n"
        'Ответь СТРОГО одним JSON без пояснений: {"category": <строка|null>, '
        '"city": <строка|null>, "province": <строка|null>}.'
    )
    try:
        client = _get_client()
        resp = await client.messages.create(
            model=config.AI_MODEL,
            max_tokens=150,
            system=system,
            messages=[{"role": "user", "content": text}],
        )
        data = _parse_json(_extract_text_and_sources(resp)[0])
    except Exception as e:  # noqa: BLE001
        log.warning("Ошибка классификации запроса ИИ: %s", e)
        return dict(empty)

    cat = data.get("category")
    if cat:
        cat_l = str(cat).strip().lower()
        cat = next((c for c in categories if c.lower() == cat_l), None)
    prov = data.get("province")
    if prov and provinces is not None:
        prov_l = str(prov).strip().lower()
        prov = next((p for p in provinces if p.lower() == prov_l), None)
    city = data.get("city")
    return {
        "category": cat,
        "city": str(city).strip() if city else None,
        "province": str(prov).strip() if prov else None,
    }


LETTER_SYSTEM = (
    "Тебе прислали ФОТО официального письма или документа из Нидерландов "
    "(например, от Belastingdienst, gemeente, IND, UWV, страховой, банка, суда). "
    "Объясни его человеку по-русски просто и спокойно, без паники. Структура ответа:\n"
    "1) От кого письмо и что это за документ.\n"
    "2) О чём оно — суть в 1–3 предложениях.\n"
    "3) Что нужно сделать (по шагам, если есть действия).\n"
    "4) Срок/дедлайн — если он указан в письме.\n"
    "5) На что обратить внимание (сумма к оплате, реквизиты, последствия).\n\n"
    "Правила: опирайся ТОЛЬКО на то, что реально видно в документе — не выдумывай "
    "суммы, даты и реквизиты. Если текст нечитаем или обрезан — честно скажи и "
    "попроси переснять чётче. Это справочное объяснение, НЕ юридическая "
    "консультация: по важным/спорным вопросам советуй обратиться к профильному "
    "специалисту или в официальный орган. Пиши обычным текстом, без разметки."
)


async def ai_explain_letter(image_b64: str, media_type: str = "image/jpeg") -> str | None:
    """Объясняет по-русски присланное фото официального письма/документа.

    Фото нигде не сохраняется — передаётся модели только для формирования ответа.
    Возвращает текст объяснения или None при ошибке/без ключа.
    """
    if not ai_enabled():
        return None
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
        {"type": "text", "text": "Объясни это письмо/документ по-русски."},
    ]
    try:
        client = _get_client()
        resp = await client.messages.create(
            model=config.AI_MODEL,
            max_tokens=900,
            system=LETTER_SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Ошибка разбора письма ИИ: %s", e)
        return None
    return _clean(_extract_text_and_sources(resp)[0]) or None


async def ai_salary(gross_month: float, ruling30: bool) -> str | None:
    """Считает примерную netto-зарплату в месяц через ИИ с веб-поиском.

    ИИ берёт АКТУАЛЬНЫЕ ставки/льготы текущего года с belastingdienst.nl, поэтому
    цифры не «протухают». Возвращает текст расчёта (с источником) или None.
    """
    if not ai_enabled():
        return None
    ruling = (
        "Работник ПОЛЬЗУЕТСЯ льготой 30%-ruling (до 30% зарплаты не облагается, в пределах лимита)."
        if ruling30 else "Без 30%-ruling."
    )
    system = (
        "Ты — калькулятор чистой (netto) зарплаты в Нидерландах. По указанной БРУТТО "
        "за месяц посчитай примерную МЕСЯЧНУЮ netto на основе АКТУАЛЬНЫХ официальных правил "
        "текущего года: ставки box 1 (loonbelasting + premies), algemene heffingskorting и "
        "arbeidskorting. Найди актуальные цифры года веб-поиском на belastingdienst.nl. "
        "Предположения: наёмный сотрудник младше пенсионного возраста (AOW), без доп. вычетов; "
        "зарплата указана без отпускных (vakantiegeld). " + ruling + "\n"
        "Ответь по-русски кратко и понятно:\n"
        "• Брутто/мес\n• Удержания (налог и взносы)\n• Налоговые льготы (heffingskortingen) — кратко\n"
        "• ИТОГО netto/мес — выдели это число\n"
        "В конце добавь строку: «Это оценка по правилам текущего года; точную сумму "
        "считает работодатель/Belastingdienst.» Пиши обычным текстом, без разметки."
    )
    user = f"Брутто-зарплата: {gross_month:.0f} евро в месяц. Посчитай netto в месяц."
    messages = [{"role": "user", "content": user}]
    client = _get_client()
    try:
        kwargs = dict(model=config.AI_MODEL, max_tokens=900, system=system, messages=messages)
        tools = _web_search_tool()
        if tools:
            kwargs["tools"] = tools
        resp = await client.messages.create(**kwargs)
    except Exception as e:  # noqa: BLE001 — пробуем без веб-поиска
        log.warning("Калькулятор зарплаты с веб-поиском не сработал (%s), пробую без", e)
        try:
            resp = await client.messages.create(
                model=config.AI_MODEL, max_tokens=900, system=system, messages=messages
            )
        except Exception as e2:  # noqa: BLE001
            log.warning("Ошибка калькулятора зарплаты ИИ: %s", e2)
            return None
    return _finalize(resp)


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
    from utils.limits import allow_ai

    user_text = (message.text or "").strip()
    if not user_text:
        return False

    uid = message.from_user.id if message.from_user else 0
    if not allow_ai(uid):
        await message.answer(
            "На сегодня ты задал уже много вопросов 🙏 Я немного передохну — "
            "загляни в меню или напиши попозже 👇",
            reply_markup=main_menu(),
        )
        return True

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
