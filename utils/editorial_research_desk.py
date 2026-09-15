"""Admin-only editorial research radar with Telegram forum-topic delivery.

This is deliberately separate from ``editorial_channel``: it proposes ideas to
the editor and never publishes anything to the public channel.  A private forum
group can be connected with /ideassetup; until then digests safely fall back to
the admin's private bot chat.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from utils import editorial_channel as editorial

log = logging.getLogger(__name__)
router = Router()
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
MAX_ATTEMPTS = 2
RETRY_MINUTES = 20
RECENT_IDEA_SLOTS = 30
_generation_lock = asyncio.Lock()


@dataclass(frozen=True)
class ResearchStream:
    key: str
    label: str
    emoji: str
    starts_at: time
    ends_at: time
    instructions: str
    domains: tuple[str, ...] = ()


_OUTPUT_RULES = (
    "Отбери максимум 5 действительно сильных тем для русскоязычных жителей Нидерландов. "
    "Не создавай готовые посты и визуалы. Не заполняй подборку слабыми вариантами: если "
    "достойных тем нет, напиши об этом прямо. Для каждой темы укажи: 1) короткий рабочий "
    "заголовок; 2) что произошло или почему тема актуальна сейчас; 3) почему она интересна "
    "аудитории Podslushano.nl; 4) оценку по 12-балльной системе: актуальность 0–3, эмоция "
    "0–3, польза 0–2, визуал 0–2, срочность 0–2; 5) площадку и формат: Telegram, Stories, "
    "пост, карусель или Reels; 6) конкретную идею визуальной подачи на реальных фото, карте, "
    "документе или официальном скриншоте; 7) прямые ссылки на подтверждённые источники. "
    "В конце дай короткий редакционный вывод: что брать первым и что оставить запасом. "
    "Пиши по-русски, живо и по-журналистски, без ИИ-штампов, markdown-таблиц и служебных фраз. "
    "Весь ответ — не более 3600 знаков."
)

_NEWS_RULES = (
    "Понимай этот поток как оперативную редакционную проверку, а не общий контентный поиск. "
    "Ищи важные новости, решения властей, законы, предупреждения и практические изменения для "
    "жизни в Нидерландах: деньги, налоги, жильё, работа, транспорт, медицина, образование и "
    "документы. Соцсети используй только для обнаружения; факты подтверждай официальным "
    "источником либо двумя независимыми надёжными источниками. Максимум две темы из криминала, "
    "аварий и пожаров; обычные локальные происшествия без широкой значимости не включай. "
    "Не забирай темы специализированных потоков про звёзд и блогеров, афишу, календарные даты, "
    "локальные истории провинций, интернет-хайп и evergreen-разборы, если в них нет срочного "
    "общественно значимого развития."
)

STREAMS: tuple[ResearchStream, ...] = (
    ResearchStream(
        "morning", "Инфоповоды — утро", "🌅", time(7, 30), time(11, 55),
        _NEWS_RULES + " Учти события ночи, предупреждения, планы на сегодня и изменения, которыми аудитория сможет воспользоваться сегодня или в ближайшие дни.",
        ("rijksoverheid.nl", "nos.nl", "nu.nl", "cbs.nl", "knmi.nl", "ns.nl", "prorail.nl", "anwb.nl", "politie.nl"),
    ),
    ResearchStream(
        "people", "Люди Нидерландов", "🎙", time(7, 40), time(11, 55),
        "Ищи за последние 24–72 часа важные, обсуждаемые или визуально сильные поводы о публичной жизни: нидерландские музыканты, актёры, телеведущие, спортсмены вне результатов, крупные блогеры и создатели контента, а также королевская семья в человеческом и общественном контексте. Проверяй официальные аккаунты, заявления и интервью. Не включай неподтверждённые сплетни и мировых знаменитостей без явной связи с Нидерландами.",
    ),
    ResearchStream(
        "events", "Афиша Нидерландов", "🎪", time(7, 50), time(11, 55),
        "Ищи крупные, ожидаемые и необычные мероприятия по всей стране на ближайшие 2–8 недель: фестивали, городские праздники, парады, ярмарки, выставки, концерты, световые и цветочные события, дни открытых дверей и редкие ежегодные события. Проверяй точные даты, город, цену, билеты, ограничения, официальный сайт и официальный Instagram. Прошедшие события запрещены. Приоритет — темы, ради которых сохранят или перешлют публикацию.",
        ("evenementen.nl", "holland.com", "iamsterdam.com", "uitagendautrecht.nl", "rotterdamfestivals.nl", "denhaag.com", "thisiseindhoven.com", "visitbrabant.com"),
    ),
    ResearchStream(
        "provinces", "Радар 12 провинций", "🗺", time(8, 0), time(11, 55),
        "Просмотри локальные и провинциальные источники всех 12 провинций. Найди истории, не попавшие в национальную повестку, но интересные всей стране: необычные инициативы, открытия, рекорды, изменения городов, редкие традиции, общественные проекты и локальные споры с человеческим сюжетом. Стремись к географическому разнообразию; не своди подборку к Амстердаму, Роттердаму и Гааге. Для каждой темы обязательно назови провинцию и город. Не включай обычную криминальную хронику и стандартные объявления gemeente.",
    ),
    ResearchStream(
        "calendar", "Календарь Нидерландов", "📅", time(8, 10), time(11, 55),
        "Проверь, что наступает сегодня, завтра и в ближайшие 30 дней: национальные и официальные памятные даты, государственные церемонии, дни флага, провинциальные и городские праздники, традиционные сезоны, локальные народные обычаи, культурные даты и юбилеи значимых событий. Это редакционный календарь, объясняющий страну, а не перечень международных «дней чего-либо». Укажи точную дату и оптимальную дату публикации; опирайся на официальные, музейные и архивные источники.",
        ("rijksoverheid.nl", "koninklijkhuis.nl", "nationaalarchief.nl", "canonvannederland.nl", "openluchtmuseum.nl", "cultureelerfgoed.nl", "holland.com"),
    ),
    ResearchStream(
        "buzz", "Что обсуждают", "💬", time(8, 20), time(11, 55),
        "Ищи темы последних 24–72 часов, заметно обсуждаемые в нидерландском интернете и массовой культуре: вирусные видео, общественные дискуссии, телевизионные моменты, потребительские тренды, заметные кампании брендов, городские привычки, мемы и споры. Подтверди тренд несколькими независимыми признаками: первоисточник, заметное вовлечение, публикации надёжных СМИ или официальная реакция. Не выдавай единичный пост за тренд и не включай слухи.",
    ),
    ResearchStream(
        "evergreen", "Неочевидные Нидерланды", "🔎", time(8, 30), time(11, 55),
        "Ищи не срочные новости, а сильные evergreen-темы для журналистского сторителлинга: инфраструктура, архитектура, вода, транспорт, жильё, язык, дизайн, наука, история, общественные правила, известные местные компании и вещи, смысл которых приезжим неочевиден. Тема должна вести от сильного хука через факты, карту, архивную вырезку, официальную схему или реальный объект к полезному или удивительному финалу. Запрещены банальности про велосипеды, тюльпаны, мельницы и уровень моря без нового сильного угла; не повторяй выпуски «Как это устроено» про huisarts и аренду. Для каждой темы предложи короткий сюжет карусели по слайдам.",
        ("canonvannederland.nl", "rijksmuseum.nl", "openluchtmuseum.nl", "cultureelerfgoed.nl", "nationaalarchief.nl", "archieven.nl", "cbs.nl", "tudelft.nl"),
    ),
    ResearchStream(
        "day", "Инфоповоды — день", "☀️", time(12, 0), time(16, 55),
        _NEWS_RULES + " Найди только новые значимые темы, появившиеся после утренней проверки, уточнения к развивающимся историям и полезные изменения, которые утром ещё нельзя было подтвердить.",
        ("rijksoverheid.nl", "nos.nl", "nu.nl", "cbs.nl", "ns.nl", "prorail.nl", "anwb.nl", "politie.nl"),
    ),
    ResearchStream(
        "evening", "Инфоповоды — вечер", "🌆", time(17, 0), time(22, 0),
        _NEWS_RULES + " Найди только новые темы после дневной проверки, подведи редакционный итог дня и отдельно отметь одну сильнейшую тему для Instagram/Facebook, если она действительно есть.",
        ("rijksoverheid.nl", "nos.nl", "nu.nl", "cbs.nl", "ns.nl", "prorail.nl", "anwb.nl", "politie.nl"),
    ),
)
STREAM_BY_KEY = {stream.key: stream for stream in STREAMS}


def _now() -> datetime:
    return datetime.now(AMSTERDAM).replace(tzinfo=None)


def _is_due(stream: ResearchStream, now: datetime) -> bool:
    return stream.starts_at <= now.time() < stream.ends_at


async def _recent_ideas() -> list[str]:
    values = []
    for index in range(RECENT_IDEA_SLOTS):
        value = await editorial._meta_get(f"research_recent_{index}")
        if value:
            values.append(value)
    return values


def _headline_signals(text: str) -> list[str]:
    signals = []
    for raw in (text or "").splitlines():
        line = re.sub(r"^[\s#*•\-–—\d.)]+", "", raw).strip()
        if 18 <= len(line) <= 95 and (re.match(r"^\d+[.)]", raw.strip()) or len(signals) < 2):
            if line.casefold() not in {item.casefold() for item in signals}:
                signals.append(line)
        if len(signals) >= 5:
            break
    return signals


async def _remember_ideas(text: str) -> None:
    fresh = _headline_signals(text)
    if not fresh:
        return
    recent = await _recent_ideas()
    merged = fresh + [old for old in recent if old.casefold() not in {x.casefold() for x in fresh}]
    for index, value in enumerate(merged[:RECENT_IDEA_SLOTS]):
        await editorial._meta_set(f"research_recent_{index}", value)


def _append_sources(text: str, sources: list[str]) -> str:
    missing = [url for url in sources if url not in text][:8]
    if not missing:
        return text.strip()
    return text.rstrip() + "\n\nИсточники поиска:\n" + "\n".join(missing)


async def _generate_digest(stream: ResearchStream) -> str | None:
    recent = await _recent_ideas()
    published = await editorial._recent_topics()
    exclusions = " | ".join((recent + published)[:24]) or "нет"
    system = (
        "Ты работаешь во внутреннем редакционном радаре Podslushano.nl. Обязательно проведи "
        "свежий веб-поиск и верни только редакционную сводку, а не рассказ о процессе поиска. "
        + stream.instructions + " " + _OUTPUT_RULES
    )
    user = (
        f"Сегодня {_now():%d.%m.%Y}, часовой пояс Europe/Amsterdam. Поток: {stream.label}. "
        f"Недавние предложенные и опубликованные темы, которые нельзя повторять без существенного нового развития: {exclusions}."
    )
    async with _generation_lock:
        result = await editorial._generate(system, user, list(stream.domains), 1900)
    if not result:
        return None
    return _append_sources(result[0], result[1])


def _split_messages(text: str, limit: int = 3800) -> list[str]:
    paragraphs = text.strip().split("\n\n")
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else current + "\n\n" + paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > limit:
            cut = paragraph.rfind("\n", 0, limit)
            if cut < limit // 2:
                cut = paragraph.rfind(" ", 0, limit)
            if cut < limit // 2:
                cut = limit
            chunks.append(paragraph[:cut].rstrip())
            paragraph = paragraph[cut:].lstrip()
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


async def _topic_destination(stream: ResearchStream) -> tuple[int | None, int | None]:
    raw_chat = await editorial._meta_get("research_desk_chat_id")
    raw_topic = await editorial._meta_get(f"research_topic_{stream.key}")
    try:
        return (int(raw_chat), int(raw_topic)) if raw_chat and raw_topic else (None, None)
    except ValueError:
        return None, None


async def _deliver_digest(bot, stream: ResearchStream, text: str) -> bool:
    header = f"{stream.emoji} {stream.label}\n{_now():%d.%m.%Y}\n\n"
    chunks = _split_messages(header + text)
    chat_id, topic_id = await _topic_destination(stream)
    targets = [(chat_id, topic_id)] if chat_id else [(admin_id, None) for admin_id in config.ADMIN_IDS]
    delivered = False
    for target_chat, target_topic in targets:
        if target_chat is None:
            continue
        try:
            for chunk in chunks:
                await bot.send_message(
                    target_chat,
                    chunk,
                    message_thread_id=target_topic,
                    parse_mode=None,
                    disable_web_page_preview=True,
                )
            delivered = True
        except Exception as exc:  # noqa: BLE001
            log.warning("Cannot deliver research stream %s to %s: %s", stream.key, target_chat, exc)
    return delivered


async def _alert_failure(bot, stream: ResearchStream, detail: str) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"⚠️ {stream.label}: сводка не подготовлена. {detail}\nПовтор будет выполнен автоматически; вручную можно запустить через /ideas.",
                parse_mode=None,
            )
        except Exception:
            pass


async def _run_stream(bot, stream: ResearchStream, now: datetime, *, force: bool = False) -> bool:
    today = now.date().isoformat()
    date_key = f"research_digest_{stream.key}_date"
    if not force and await editorial._meta_get(date_key) == today:
        return False
    if not force and not _is_due(stream, now):
        return False

    attempt_key = f"research_digest_{stream.key}_attempts_{today}"
    cooldown_key = f"research_digest_{stream.key}_try"
    try:
        attempts = int(await editorial._meta_get(attempt_key) or "0")
    except ValueError:
        attempts = 0
    if not force:
        if attempts >= MAX_ATTEMPTS:
            return False
        if not await editorial._attempt_allowed(cooldown_key, now, RETRY_MINUTES):
            return False
        await editorial._meta_set(attempt_key, attempts + 1)

    try:
        text = await _generate_digest(stream)
    except Exception as exc:  # noqa: BLE001
        log.exception("Research stream %s failed", stream.key)
        if not force:
            await _alert_failure(bot, stream, f"Ошибка {type(exc).__name__}.")
        return False
    if not text:
        if not force:
            await _alert_failure(bot, stream, "Web Search не вернул проверенный результат.")
        return False
    if not await _deliver_digest(bot, stream, text):
        return False

    await _remember_ideas(text)
    if not force:
        await editorial._meta_set(date_key, today)
    return True


def _ideas_menu() -> InlineKeyboardMarkup:
    rows = []
    for stream in STREAMS:
        rows.append([InlineKeyboardButton(text=f"{stream.emoji} {stream.label}", callback_data=f"ideas:{stream.key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("ideas", "editorialdesk"))
async def ideas_command(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    chat_id, _ = await _topic_destination(STREAMS[0])
    destination = "отдельные темы редакционной группы" if chat_id else "личный чат с ботом"
    await message.answer(
        "🧭 Редакционный радар\n\n"
        "Все 9 потоков активны. Автоматическая доставка: 07:30–08:30, 12:00 и 17:00.\n"
        f"Сейчас результаты направляются в: {destination}.\n\n"
        "Нажмите категорию, чтобы запустить внеплановую проверку прямо сейчас.",
        parse_mode=None,
        reply_markup=_ideas_menu(),
    )


@router.callback_query(F.data.startswith("ideas:"), F.from_user.id.in_(config.ADMIN_IDS))
async def ideas_callback(callback: CallbackQuery) -> None:
    stream = STREAM_BY_KEY.get(callback.data.split(":", 1)[1])
    if not stream:
        await callback.answer("Неизвестная категория", show_alert=True)
        return
    await callback.answer("Ищу и проверяю темы…")
    ok = await _run_stream(callback.bot, stream, _now(), force=True)
    await callback.message.answer(
        f"{'✅ Готово' if ok else '❌ Не удалось подготовить'}: {stream.label}",
        parse_mode=None,
    )


@router.message(Command("ideassetup"))
async def ideas_setup_command(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    if message.chat.type != "supergroup" or not getattr(message.chat, "is_forum", False):
        await message.answer(
            "Эту команду нужно запустить в закрытой Telegram-супергруппе с включёнными темами. "
            "Добавьте бота администратором с правом управления темами и снова отправьте /ideassetup.",
            parse_mode=None,
        )
        return
    existing_chat = await editorial._meta_get("research_desk_chat_id")
    existing_topics = [await editorial._meta_get(f"research_topic_{stream.key}") for stream in STREAMS]
    if existing_chat == str(message.chat.id) and all(existing_topics):
        await message.answer("✅ Эта редакционная группа уже подключена: все 9 тем настроены.", parse_mode=None)
        return

    created: list[str] = []
    try:
        for stream in STREAMS:
            topic = await message.bot.create_forum_topic(message.chat.id, name=f"{stream.emoji} {stream.label}")
            await editorial._meta_set(f"research_topic_{stream.key}", topic.message_thread_id)
            created.append(stream.label)
        await editorial._meta_set("research_desk_chat_id", message.chat.id)
    except Exception as exc:  # noqa: BLE001
        log.exception("Editorial research forum setup failed")
        await message.answer(
            f"❌ Не удалось создать все темы: {type(exc).__name__}. Проверьте, что бот — администратор и может управлять темами.",
            parse_mode=None,
        )
        return
    await message.answer(
        "✅ Редакционная группа подключена. Созданы отдельные темы:\n\n" + "\n".join(f"• {name}" for name in created),
        parse_mode=None,
    )


async def editorial_research_loop(bot) -> None:
    await asyncio.sleep(50)
    while True:
        try:
            now = _now()
            for stream in STREAMS:
                await _run_stream(bot, stream, now)
        except Exception as exc:  # noqa: BLE001
            log.exception("Editorial research loop failed: %s", exc)
        await asyncio.sleep(60)
