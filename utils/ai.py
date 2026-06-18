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
import re
from datetime import date
from urllib.parse import urlparse

import config

log = logging.getLogger(__name__)

# Клиент создаётся один раз (лениво), чтобы не дёргать сеть при импорте.
_client = None

# Сколько последних реплик помним в диалоге (пар «пользователь — бот»).
# Меньше история — меньше входных токенов в каждом запросе (экономия).
HISTORY_LIMIT = 4

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
    "• Вопросы про мероприятия/афишу/«что сегодня или на выходных в городе»: "
    "ОБЯЗАТЕЛЬНО воспользуйся веб-поиском и постарайся назвать КОНКРЕТНЫЕ события — "
    "название, дату, место и ссылку. Смотри местные афиши (uitagenda, сайт VVV "
    "города, iamsterdam.com, eventbrite, ticketmaster, songkick) и сайт gemeente. "
    "Если город маленький и на нужную дату конкретного ничего не нашлось — честно "
    "скажи это и предложи афишу ближайшего крупного города (или ближайшие даты). "
    "НИКОГДА не выдумывай несуществующие мероприятия — лучше честно, чем выдумка.\n"
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
            model=config.AI_CHAT_MODEL,
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


# Случайные HTML-теги от модели (только настоящие теги, не «x < 5 и y > 3»)
_HTML_TAG_RE = re.compile(
    r"</?(?:b|strong|i|em|u|s|strike|del|code|pre|a|br|p|span|div|ul|ol|li|"
    r"blockquote|tg-spoiler|h[1-6])\b[^>]*>",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    """Убирает остатки markdown и случайные HTML-теги от модели.

    Свободные ответы шлём обычным текстом (parse_mode=None) — там теги вроде
    <b>…</b> вылезли бы «голыми». А разбор письма и зарплату вставляем в наш
    HTML-шаблон — там кривой тег модели мог бы сломать разбор у Telegram.
    Поэтому в обоих случаях срезаем и markdown-маркеры, и HTML-теги.
    """
    text = text.replace("**", "").replace("__", "")
    return _HTML_TAG_RE.sub("", text)


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
        "- Возвращай category ТОЛЬКО если запрос явно соответствует одной из "
        "категорий списка. Если ищут услугу/профессию, которой НЕТ в списке "
        "(например: автомойка, химчистка, клининг, грумер, эвакуатор, ремонт авто, "
        "доставка, аренда авто) — category=null. НЕ подгоняй под похожую категорию.\n"
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


_INTENT_SYSTEM = (
    "Ты — маршрутизатор сообщений для бота-помощника русскоязычных в Нидерландах. "
    "Определи НАМЕРЕНИЕ пользователя и верни СТРОГО JSON: "
    '{"intent": "specialist" | "info" | "chat"}.\n\n'
    "- specialist — пользователь хочет НАЙТИ или НАНЯТЬ конкретного специалиста/"
    "мастера/контакт. Примеры: «нужен стоматолог в Гааге», «посоветуйте юриста», "
    "«ищу няню», «фотограф на свадьбу», «к кому из бухгалтеров обратиться».\n"
    "- info — пользователь задаёт ВОПРОС, просит совет/инструкцию/информацию/ссылку, "
    "или прямо говорит, что специалист НЕ нужен. Примеры: «что делать, если просрочил "
    "налоговую декларацию», «как оформить BSN», «какие штрафы за…», «сколько стоит виза», "
    "«не ищу бухгалтера, нужен совет», «объясни про toeslag».\n"
    "- chat — приветствие, благодарность, болтовня, не по теме.\n\n"
    "Важно: само упоминание профессии (бухгалтер, юрист, врач…) НЕ делает это "
    "specialist — смотри, человек ИЩЕТ контакт или просто спрашивает по теме. Если "
    "пользователь пишет, что НЕ ищет специалиста — это info. Сомневаешься — выбирай info."
)


_POST_SYSTEM = (
    "Ты — редактор Telegram-канала сообщества русскоязычных в Нидерландах. Пишешь "
    "как человек, который ДАВНО живёт в NL и хорошо знает тему: экспертно, чётко, "
    "по делу. ОБЯЗАТЕЛЬНО используй веб-поиск для фактов, цифр, адресов и ссылок — "
    "ничего не выдумывай.\n\n"
    "Задача: написать ОДИН готовый пост для канала на заданную тему. На любую тему, "
    "которую задаёт редактор (места, события, приезд гостей/звёзд, документы, быт, "
    "кухня, лайфхаки), — пиши пост, не отказывайся и не предлагай обратиться "
    "куда-то ещё.\n\n"
    "Тон и стиль:\n"
    "- чётко, структурно, без воды, без фамильярности, сленга и грубостей;\n"
    "- нейтрально-уважительно, без обращения «ты», как полезная редакционная заметка;\n"
    "- конкретика: факты, шаги, цифры, официальные источники, где уместно;\n"
    "- все названия мест, городов, провинций, госучреждений, организаций пиши на "
    "ЯЗЫКЕ ОРИГИНАЛА (нидерландском/английском), НЕ транслитерируй на русский: "
    "Schiermonnikoog, Waddenzee, Gelderland, Den Haag, Belastingdienst, Gemeente, "
    "DigiD. Можно дать краткий перевод в скобках при первом упоминании.\n\n"
    "Формат:\n"
    "- цепляющий заголовок ПЕРВОЙ строкой в <b>…</b>;\n"
    "- 2–3 смысловых блока с короткими подзаголовками в <b>…</b> и списками («• …»);\n"
    "- умеренно эмодзи (по смыслу, не больше одного на блок);\n"
    "- в конце — короткий практичный вывод/совет, а затем отдельной строкой "
    "ненавязчивый призыв поставить реакцию 🔥, если пост был полезен "
    "(по теме поста, без фамильярности и панибратства).\n\n"
    "ОБЪЁМ — ЖЁСТКОЕ ПРАВИЛО: весь пост (без учёта строки IMG_QUERY) должен "
    "уместиться в 900 символов и НИ В КОЕМ СЛУЧАЕ не превышать 1000 — это подпись "
    "к фото в Telegram, всё, что сверху лимита, обрежется. Лучше короче и плотнее: "
    "не перечисляй всё подряд, дай только самое важное. Если тема большая (много "
    "пунктов) — НЕ описывай каждый, а выбери 2–3 главных или дай обзор одним абзацем.\n\n"
    "СТРОГО ЗАПРЕЩЕНО:\n"
    "- описывать свои действия и процесс («сейчас поищу», «у меня достаточно "
    "данных», «составляю пост», «на основе найденной информации», «отлично» и т.п.) "
    "— выдавай ТОЛЬКО готовый пост, как будто его написал человек;\n"
    "- любые вступления и комментарии до заголовка — начинай СРАЗУ с заголовка "
    "в <b>…</b>;\n"
    "- разделительные линии (---, ***, ===, ___) и горизонтальные черты.\n\n"
    "Технически: по-русски. Разметка ТОЛЬКО тегами <b> и <i> (для Telegram); никаких "
    "#, *, markdown и других тегов. Ссылки — обычным текстом (https://…). Пост идёт "
    "С ФОТО, поэтому уложись в ~900 символов (это подпись к фото).\n\n"
    "В САМОМ КОНЦЕ отдельной строкой добавь: «IMG_QUERY: <2–4 английских ключевых "
    "слова для подбора тематического стокового фото>». Эта строка — служебная, не "
    "часть поста."
)


def _clean_post(text: str) -> tuple[str, str]:
    """Чистит сгенерированный пост и вынимает служебную строку IMG_QUERY.

    Убирает преамбулу-болталку модели до заголовка, разделительные линии и
    строку IMG_QUERY. Возвращает (текст_поста, image_query)."""
    image_query = ""
    lines = text.splitlines()
    cleaned: list[str] = []
    for ln in lines:
        # Служебная строка с ключевыми словами для фото (может прийти с тегами)
        bare = re.sub(r"<[^>]+>", "", ln).strip()
        m = re.match(r"IMG_QUERY:\s*(.+)", bare, re.IGNORECASE)
        if m:
            image_query = m.group(1).strip().strip('"').strip()
            continue
        # Разделительные линии вида ---, ***, ===, ___, длинные тире
        if re.fullmatch(r"[\-\*=_—–\s]{3,}", ln.strip()):
            continue
        cleaned.append(ln)
    # Срезаем преамбулу: если есть заголовок в <b>, всё до него — это болтовня
    joined = "\n".join(cleaned)
    idx = joined.find("<b>")
    if idx > 0:
        joined = joined[idx:]
    return joined.strip(), image_query


async def ai_channel_post(topic: str) -> tuple[str, str] | None:
    """Готовый структурный пост для канала по теме. Возвращает (текст, image_query)
    или None. image_query — англ. ключевые слова для подбора фото из стока."""
    if not ai_enabled() or not (topic or "").strip():
        return None
    messages = [{"role": "user", "content": f"Тема поста: {topic.strip()}"}]
    client = _get_client()
    try:
        kwargs = dict(model=config.AI_POST_MODEL, max_tokens=1400, system=_POST_SYSTEM,
                      messages=messages)
        tools = _web_search_tool()
        if tools:
            kwargs["tools"] = tools
        resp = await client.messages.create(**kwargs)
    except Exception as e:  # noqa: BLE001 — пробуем без веб-поиска
        log.warning("Пост с веб-поиском не сработал (%s), пробую без", e)
        try:
            resp = await client.messages.create(
                model=config.AI_POST_MODEL, max_tokens=1400, system=_POST_SYSTEM,
                messages=messages,
            )
        except Exception as e2:  # noqa: BLE001
            log.warning("Ошибка ai_channel_post: %s", e2)
            return None
    text = _extract_text_and_sources(resp)[0].strip()
    if not text:
        return None
    text, image_query = _clean_post(text)
    if not text:
        return None
    # Фото ищем по АНГЛИЙСКИМ ключевым словам. Если модель их не дала — генерим
    # отдельно (сток плохо ищет по русскому запросу темы).
    if not image_query:
        image_query = await ai_image_keywords(topic)
    return text, image_query


async def ai_image_keywords(topic: str) -> str:
    """2–4 английских ключевых слова для подбора стокового фото по теме."""
    if not ai_enabled() or not (topic or "").strip():
        return ""
    try:
        resp = await _get_client().messages.create(
            model=config.AI_CHAT_MODEL,
            max_tokens=30,
            system=(
                "Return 2-4 English keywords to find a relevant stock photo for the "
                "given topic. Answer with ONLY the keywords, nothing else."
            ),
            messages=[{"role": "user", "content": topic.strip()}],
        )
        kw = _extract_text_and_sources(resp)[0]
        return re.sub(r"<[^>]+>", "", kw).strip().strip('"').strip()
    except Exception as e:  # noqa: BLE001
        log.warning("ai_image_keywords error: %s", e)
        return ""


_IG_SYSTEM = (
    "Ты — редактор Instagram-аккаунта сообщества русскоязычных в Нидерландах. "
    "Готовишь материал для поста-карусели (формат 4:5). Пишешь экспертно, чётко, "
    "по делу, без фамильярности, сленга и грубостей, как человек, который давно "
    "живёт в NL. ОБЯЗАТЕЛЬНО используй веб-поиск для фактов, цифр, адресов и "
    "ссылок — ничего не выдумывай.\n\n"
    "Верни СТРОГО ОДИН JSON-объект (без markdown, без пояснений) такой структуры:\n"
    "{\n"
    '  "type": "carousel" | "single",\n'
    '  "headline": "цепляющий заголовок для 1-го слайда (хук, до 60 знаков)",\n'
    '  "cover_img_query": "2-4 english keywords for the cover photo",\n'
    '  "slides": [ {"title": "короткий заголовок слайда (до 40 знаков)", '
    '"body": "1-3 коротких предложения по сути (до 180 знаков)", '
    '"img_query": "2-4 english keywords for this slide photo"} ],\n'
    '  "cta": {"title": "короткий призыв (до 40 знаков), напр. ПОНРАВИЛОСЬ?", '
    '"body": "что сделать: сохранить пост, подписаться, написать в комментариях '
    '(до 160 знаков)", "img_query": "2-4 english keywords for cta photo"},\n'
    '  "caption": "подпись под постом в Instagram: 2-4 предложения сути + в конце '
    'ненавязчивый призыв сохранить/поставить лайк. Без ссылок (в Instagram они не '
    'кликаются), эмодзи умеренно",\n'
    '  "hashtag": "#pnl_места"\n'
    "}\n\n"
    "Правила:\n"
    "- carousel: 1 обложка (headline) + 4–6 слайдов в массиве slides + 1 финальный "
    "слайд cta (итого 6–8). Для короткой новости/одного факта используй type=single, "
    "slides=[] (но cta всё равно заполни).\n"
    "- ВЕСЬ текст — обычный, БЕЗ HTML, markdown, символов #, * и звёздочек "
    "(он ляжет прямо на картинку и в подпись).\n"
    "- по-русски; заголовки и тексты слайдов короткие и читаемые на телефоне;\n"
    "- ВАЖНО: все названия мест, городов, провинций, госучреждений, организаций и "
    "брендов пиши на ЯЗЫКЕ ОРИГИНАЛА (нидерландском/английском), НЕ транслитерируй "
    "на русский: пиши Schiermonnikoog (не «Схермонникоог»), Waddenzee, Gelderland, "
    "Den Haag, Belastingdienst, Gemeente, DigiD. Можно дать краткий перевод в "
    "скобках при первом упоминании, если без него непонятно;\n"
    "- каждый слайд — про ОДИН пункт/мысль, конкретика и польза;\n"
    "- img_query — КОНКРЕТНЫЙ визуальный запрос на английском (реальное место, "
    "объект или сцена из этого слайда), а не абстракция. Если в слайде есть "
    "название места/города в Нидерландах — добавь его и страну (напр. "
    "'Amelisweerd forest Utrecht Netherlands', 'Biesbosch national park boat'). "
    "Так фото со стока будет точно по теме;\n"
    "- hashtag: РОВНО ОДИН хэштег. Выбери #pnl_места — если пост про места, города, "
    "достопримечательности, природу, путешествия по NL; иначе #pnl_нидерланды.\n"
    "- НЕ описывай свои действия и процесс — верни только JSON."
)


# Разрешённые хэштеги (всегда ровно один под постом)
IG_HASHTAGS = {"#pnl_места", "#pnl_нидерланды"}
IG_HASHTAG_DEFAULT = "#pnl_нидерланды"


async def ai_instagram_carousel(topic: str) -> dict | None:
    """Контент для Instagram-карусели по теме. Возвращает dict со структурой
    _IG_SYSTEM (type/headline/cover_img_query/slides/caption/hashtags) или None.
    Фото НЕ подбирает — только текст и англ. запросы (img_query) для фото."""
    if not ai_enabled() or not (topic or "").strip():
        return None
    messages = [{"role": "user", "content": f"Тема поста: {topic.strip()}"}]
    client = _get_client()
    try:
        kwargs = dict(model=config.AI_POST_MODEL, max_tokens=2000, system=_IG_SYSTEM,
                      messages=messages)
        tools = _web_search_tool()
        if tools:
            kwargs["tools"] = tools
        resp = await client.messages.create(**kwargs)
    except Exception as e:  # noqa: BLE001 — пробуем без веб-поиска
        log.warning("IG-карусель с веб-поиском не сработала (%s), пробую без", e)
        try:
            resp = await client.messages.create(
                model=config.AI_POST_MODEL, max_tokens=2000, system=_IG_SYSTEM,
                messages=messages,
            )
        except Exception as e2:  # noqa: BLE001
            log.warning("Ошибка ai_instagram_carousel: %s", e2)
            return None
    data = _parse_json(_extract_text_and_sources(resp)[0])
    if not data or not data.get("headline"):
        return None
    # Нормализуем
    data["type"] = "single" if data.get("type") == "single" else "carousel"
    slides = data.get("slides")
    if not isinstance(slides, list):
        slides = []
    data["slides"] = [s for s in slides if isinstance(s, dict) and (s.get("title") or s.get("body"))]
    if data["type"] == "carousel" and not data["slides"]:
        data["type"] = "single"
    # Ровно один разрешённый хэштег
    raw = data.get("hashtag") or data.get("hashtags")
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    tag = (raw or "").strip().split()[0] if (raw or "").strip() else ""
    if not tag.startswith("#"):
        tag = "#" + tag if tag else ""
    data["hashtag"] = tag if tag in IG_HASHTAGS else IG_HASHTAG_DEFAULT
    # CTA-слайд (финальный призов): нормализуем
    cta = data.get("cta")
    if not (isinstance(cta, dict) and (cta.get("title") or cta.get("body"))):
        cta = {
            "title": "ПОНРАВИЛОСЬ?",
            "body": "Сохрани пост, чтобы не потерять, и подпишись — у нас ещё много полезного о жизни в Нидерландах.",
            "img_query": data.get("cover_img_query") or "",
        }
    data["cta"] = cta
    if not data.get("cover_img_query"):
        data["cover_img_query"] = await ai_image_keywords(topic)
    return data


async def classify_intent(text: str) -> str:
    """Намерение свободного сообщения: 'specialist' | 'info' | 'chat'.

    При недоступности ИИ или ошибке возвращает '' (вызывающий код решает сам).
    По умолчанию при неуверенности — 'info' (лучше ответить, чем навязать спеца)."""
    if not ai_enabled() or not (text or "").strip():
        return ""
    try:
        client = _get_client()
        resp = await client.messages.create(
            model=config.AI_MODEL,
            max_tokens=20,
            system=_INTENT_SYSTEM,
            messages=[{"role": "user", "content": text[:600]}],
        )
        data = _parse_json(_extract_text_and_sources(resp)[0])
    except Exception as e:  # noqa: BLE001
        log.warning("Ошибка классификации намерения: %s", e)
        return ""
    intent = str(data.get("intent", "")).strip().lower()
    return intent if intent in ("specialist", "info", "chat") else "info"


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
            model=config.AI_VISION_MODEL,
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
        kwargs = dict(model=config.AI_CHAT_MODEL, max_tokens=900, system=system, messages=messages)
        tools = _web_search_tool()
        if tools:
            kwargs["tools"] = tools
        resp = await client.messages.create(**kwargs)
    except Exception as e:  # noqa: BLE001 — пробуем без веб-поиска
        log.warning("Калькулятор зарплаты с веб-поиском не сработал (%s), пробую без", e)
        try:
            resp = await client.messages.create(
                model=config.AI_CHAT_MODEL, max_tokens=900, system=system, messages=messages
            )
        except Exception as e2:  # noqa: BLE001
            log.warning("Ошибка калькулятора зарплаты ИИ: %s", e2)
            return None
    return _finalize(resp)


async def ai_events(city: str, season_phrase: str) -> str | None:
    """Подборка «чем заняться»: реальные события на ближайшие дни + сезонные идеи.

    city == "__all__" — по всей стране (крупные события). season_phrase — «этим
    летом» и т.п. Берёт события веб-поиском (не выдумывает). Возвращает текст с
    источником или None.
    """
    if not ai_enabled():
        return None
    nationwide = city == "__all__"
    where = "по всей Нидерландам" if nationwide else f"в городе {city} и рядом"
    today = date.today().strftime("%d.%m.%Y")
    system = (
        "Ты — местный гид по Нидерландам для русскоязычных. Подскажи, чем заняться "
        f"{season_phrase} {where}. ОБЯЗАТЕЛЬНО воспользуйся веб-поиском и дай два блока:\n"
        "🎟 События — 3–6 конкретных мероприятий на ближайшие дни и выходные: название, "
        "дату и место, и ссылку, если есть. Ищи в местных афишах (uitagenda, сайт VVV "
        "города, iamsterdam.com, eventbrite, ticketmaster, songkick) и на сайте gemeente.\n"
        "💡 Идеи — 3–5 сезонных идей чем заняться (пляжи, парки, маршруты, поездки рядом, "
        "сезонные активности), привязанных к городу и сезону.\n\n"
        "Правила: по-русски, тепло и кратко, ОБЫЧНЫМ текстом без разметки и markdown. "
        "НЕ выдумывай несуществующие события — если для маленького города конкретики "
        "мало, честно скажи и предложи афишу ближайшего крупного города. Начинай сразу "
        "с подборки, без вступлений вроде «сейчас поищу»."
    )
    user = f"Чем заняться {season_phrase}? Где: {where}. Сегодня {today}."
    messages = [{"role": "user", "content": user}]
    client = _get_client()
    try:
        kwargs = dict(model=config.AI_CHAT_MODEL, max_tokens=1100, system=system, messages=messages)
        tools = _web_search_tool()
        if tools:
            kwargs["tools"] = tools
        resp = await client.messages.create(**kwargs)
    except Exception as e:  # noqa: BLE001 — пробуем без веб-поиска
        log.warning("Подборка событий с веб-поиском не сработала (%s), пробую без", e)
        try:
            resp = await client.messages.create(
                model=config.AI_CHAT_MODEL, max_tokens=1100, system=system, messages=messages
            )
        except Exception as e2:  # noqa: BLE001
            log.warning("Ошибка ai_events: %s", e2)
            return None
    return _finalize(resp)


async def ai_afisha_channel(city: str, season_phrase: str) -> str | None:
    """Афиша для публикации в Telegram-канал: ТОЛЬКО события, без блока «идеи»,
    зато много — 10–20 реальных мероприятий. Компактно (строка-две на событие),
    чтобы влезть в один пост. Берёт события веб-поиском (не выдумывает).
    """
    if not ai_enabled():
        return None
    nationwide = city == "__all__"
    where = "по всей Нидерландам" if nationwide else f"в городе {city} и рядом"
    today = date.today().strftime("%d.%m.%Y")
    system = (
        "Ты — местный гид по Нидерландам для русскоязычных. Собери НАСТОЯЩУЮ афишу "
        f"мероприятий {season_phrase} {where} для поста в Telegram-канал. "
        "ОБЯЗАТЕЛЬНО воспользуйся веб-поиском.\n\n"
        "Дай ТОЛЬКО список событий (НИКАКИХ «идей», маршрутов и общих советов): "
        "10–20 конкретных мероприятий на ближайшие дни и недели — концерты, "
        "фестивали, выставки, ярмарки, спектакли, спортивные и городские события. "
        "Ищи в местных афишах (uitagenda, сайт VVV города, iamsterdam.com, eventbrite, "
        "ticketmaster, songkick) и на сайтах gemeente.\n\n"
        "Каждое мероприятие оформляй СТРОГО по этой структуре, четырьмя строками, "
        "и отделяй события друг от друга пустой строкой:\n"
        "N. Название\n"
        "Краткое описание в ОДНО предложение (что это и чем интересно).\n"
        "📅 Дата и место (город)\n"
        "🔗 ссылка на событие или билеты\n\n"
        "Ссылку (🔗) указывай у КАЖДОГО события — официальный сайт события, страницу "
        "билетов или афишу. Если ссылку найти не удалось — НЕ выдумывай: пропусти "
        "строку 🔗 у этого события (но старайся найти для большинства).\n\n"
        "Названия городов, провинций, районов, площадок, парков, музеев и улиц пиши "
        "НА ЯЗЫКЕ ОРИГИНАЛА (латиницей, как в Нидерландах), без транслитерации на "
        "русский: например Vondelpark, Amsterdam, Den Haag, Noord-Holland, Museumplein, "
        "Rotterdam Ahoy — а НЕ «Вонделпарк», «Амстердам», «Гаага». Сами названия "
        "событий тоже оставляй как в оригинале.\n\n"
        "Правила: описания — по-русски, ОБЫЧНЫМ текстом без markdown (без ---, без #, "
        "без **). Описание держи коротким — это лента афиши, а не статья. НЕ выдумывай "
        "несуществующие события: бери только реальные из поиска. Если для маленького "
        "города событий мало — добавь события ближайшего крупного города и соседних, "
        "чтобы набрать список.\n\n"
        "ОЧЕНЬ ВАЖНО: НЕ пиши никаких вступлений и заключений — никаких «вот афиша», "
        "«сейчас поищу», «хорошего лета». Выводи ТОЛЬКО нумерованный список событий: "
        "самая первая строка ответа должна начинаться с «1.»."
    )
    user = (
        f"Собери афишу из 10–20 реальных мероприятий {season_phrase}. "
        f"Где: {where}. Сегодня {today}."
    )
    messages = [{"role": "user", "content": user}]
    client = _get_client()
    try:
        kwargs = dict(model=config.AI_CHAT_MODEL, max_tokens=2800, system=system, messages=messages)
        tools = _web_search_tool()
        if tools:
            kwargs["tools"] = tools
        resp = await client.messages.create(**kwargs)
    except Exception as e:  # noqa: BLE001 — пробуем без веб-поиска
        log.warning("Афиша для канала с веб-поиском не сработала (%s), пробую без", e)
        try:
            resp = await client.messages.create(
                model=config.AI_CHAT_MODEL, max_tokens=2800, system=system, messages=messages
            )
        except Exception as e2:  # noqa: BLE001
            log.warning("Ошибка ai_afisha_channel: %s", e2)
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
    from keyboards.menus import ANSWER_FOOTER, answer_kb
    # Главное меню остаётся снизу (reply-клавиатура «прилипает»), а под ответом —
    # кнопки «Поделиться» (личная реферальная ссылка) и «ответил не по теме».
    # Подпись в конце сохраняет ссылку на бота в пересланном/заскриненном ответе.
    await message.answer(
        reply + ANSWER_FOOTER, reply_markup=answer_kb(uid), parse_mode=None
    )
    from utils.analytics import log_event
    await log_event("ai")
    return True
