"""Hardening for the 21:00 editorial pipeline.

The evening post is intentionally two-stage:
1) a real Anthropic Web Search gathers verified facts + sources;
2) a normal model call writes the final human Telegram post from that verified research.

This avoids the old failure mode where one request had to both search and return
a polished final answer with citations, causing valid evening generations to be
rejected as ``None`` while the rest of the editorial system worked.
"""
from __future__ import annotations

from aiogram.types import Message

import config
from utils import editorial_channel as editorial
from utils import editorial_overrides as overrides

# Use source families already proven by the working curiosity/event pipelines.
EVENING_RESEARCH_GROUPS = (
    [
        "canonvannederland.nl",
        "rijksmuseum.nl",
        "openluchtmuseum.nl",
        "cultureelerfgoed.nl",
        "stadsarchief.amsterdam.nl",
        "archieven.nl",
        "holland.com",
    ],
    [
        "holland.com",
        "iamsterdam.com",
        "cbs.nl",
        "rijksoverheid.nl",
        "government.nl",
    ],
)


async def _research_evening_topic() -> tuple[str, list[str]] | None:
    """Find one verified non-banal evening topic. Returns research + real URLs."""
    recent = await editorial._recent_topics()
    research_system = (
        "Ты фактчекер вечерней рубрики русскоязычного Telegram-медиа о Нидерландах. "
        "Сделай веб-поиск и найди ОДИН конкретный небанальный сюжет для одной из двух рубрик: "
        "«История одного места/предмета» или «Почему здесь так?». "
        "Нужен материал, который интересен людям, уже живущим в Нидерландах. "
        "Не бери банальности про уровень моря, велосипеды, тюльпаны, кофешопы, красные фонари, "
        "мельницы, деревянные башмаки и прямолинейность голландцев. "
        "Проверь факты через веб-поиск. В ответе дай рабочие заметки для редактора: конкретная тема, "
        "4-7 проверенных фактов, почему это интересно сейчас/сегодня и важные оговорки. "
        "Это НЕ финальный пост, поэтому можно писать структурно."
    )
    user = (
        f"Сегодня {editorial._now():%d.%m.%Y}. Не повторяй последние темы: "
        f"{', '.join(recent) or 'нет'}. Обязательно используй веб-поиск."
    )

    for domains in EVENING_RESEARCH_GROUPS:
        try:
            result = await editorial._generate(research_system, user, domains, 1000)
        except Exception as exc:  # noqa: BLE001
            editorial.log.exception("Evening research request crashed: %s", exc)
            continue
        if not result:
            editorial.log.warning("Evening research group returned no verified result: %s", domains)
            continue
        research, sources = result
        if research and sources and len(research.strip()) >= 180:
            return research.strip(), sources
    return None


async def _write_evening_post(research: str, sources: list[str]) -> str | None:
    """Turn already verified research into the final 21:00 Telegram post."""
    system = (
        "Ты вечерний редактор Telegram-канала для русскоязычных людей, которые уже живут в Нидерландах. "
        "На основе ТОЛЬКО предоставленных проверенных редакционных заметок напиши один живой пост. "
        "Рубрика должна быть либо «История одного места/предмета», либо «Почему здесь так?». "
        "Начни с сильной конкретной детали или интриги, затем объясни историю/причину человеческим языком. "
        "Не описывай процесс поиска, не пиши «мы нашли», «я выбрал», «материал найден», «по данным источников». "
        "Не придумывай фактов сверх заметок. Не делай подборку. Не начинай с «А вы знали?». "
        "550-780 знаков. Без markdown, HTML и служебных комментариев. Верни ТОЛЬКО готовый пост."
    )
    source_lines = "\n".join(f"- {url}" for url in sources[:6])
    user = (
        "ПРОВЕРЕННЫЕ РЕДАКЦИОННЫЕ ЗАМЕТКИ:\n"
        f"{research}\n\n"
        "ИСТОЧНИКИ, использованные на этапе фактчекинга:\n"
        f"{source_lines}\n\n"
        "Теперь напиши только финальный Telegram-пост."
    )
    try:
        response = await editorial._get_client().messages.create(
            model=config.AI_POST_MODEL,
            max_tokens=900,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as exc:  # noqa: BLE001
        editorial.log.exception("Evening writing request crashed: %s", exc)
        return None

    text, _ = editorial._extract_text_and_sources(response)
    text = editorial._clean_text(text)
    if len(text.strip()) < 220:
        editorial.log.warning("Evening writer returned too little text")
        return None
    return text.strip()


async def _robust_evening_post() -> str | None:
    research = await _research_evening_topic()
    if not research:
        editorial.log.warning("Evening pipeline failed at research stage")
        return None
    notes, sources = research
    final = await _write_evening_post(notes, sources)
    if not final:
        editorial.log.warning("Evening pipeline failed at writing stage")
        return None
    return final


async def _real_web_health() -> tuple[bool, str]:
    if not config.ANTHROPIC_API_KEY:
        return False, "ANTHROPIC_API_KEY отсутствует"
    if not config.AI_WEB_SEARCH:
        return False, "AI_WEB_SEARCH выключен"
    try:
        result = await editorial._generate(
            "Обязательно выполни веб-поиск на knmi.nl и ответь одним коротким предложением по-русски. Не отвечай из памяти.",
            "Это технический health-check реального Anthropic Web Search.",
            ["knmi.nl"],
            180,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"реальный запрос упал: {type(exc).__name__}: {exc}"
    if not result or not result[0]:
        return False, "реальный Web Search вернул пустой/непроверенный результат"
    return True, "реальный Anthropic Web Search успешно вернул проверенный текст"


async def editorial_health_real(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await message.answer("🔎 Проверяю реальный редакционный пайплайн…")
    web_ok, web_detail = await _real_web_health()
    openai_ok, openai_detail = await overrides._check_openai_image_access()
    channel_ok, channel_detail = await overrides._channel_health(message.bot)
    lines = [
        "🩺 Editorial Health · REAL",
        "",
        f"{'✅' if web_ok else '❌'} Anthropic + Web Search: {web_detail}",
        f"{'✅' if openai_ok else '❌'} OpenAI Images: {openai_detail}",
        f"{'✅' if channel_ok else '❌'} Канал/права: {channel_detail}",
        f"{'✅' if config.ADMIN_IDS else '❌'} ADMIN_IDS: {len(config.ADMIN_IDS)} админ(а/ов)",
        "",
        "Этот тест делает настоящий Web Search запрос, а не просто проверяет наличие ключа.",
    ]
    await message.answer("\n".join(lines), parse_mode=None)


def _replace_health_handler() -> None:
    try:
        for handler in overrides.router.message.handlers:
            callback = getattr(handler, "callback", None)
            if getattr(callback, "__name__", "") == "editorial_health_command":
                handler.callback = editorial_health_real
                return
    except Exception as exc:  # noqa: BLE001
        editorial.log.warning("Could not replace editorial health handler: %s", exc)


def install_editorial_websearch_fix() -> None:
    # One source of truth for BOTH scheduler and manual preview.
    overrides._focused_evening_post = _robust_evening_post
    editorial._evening_post = _robust_evening_post
    _replace_health_handler()


# Keep compatibility with startup stacks that wrap overrides.install.
_original_install = overrides.install


def _wrapped_install() -> None:
    _original_install()
    install_editorial_websearch_fix()


overrides.install = _wrapped_install
