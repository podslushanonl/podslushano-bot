"""Hardening for editorial Anthropic Web Search.

Fixes the 21:00 path by using source whitelists known to be accepted by the
Anthropic web-search user agent. A single inaccessible domain makes Anthropic
reject the whole request with HTTP 400, so unsupported domains must never be
sent in allowed_domains.
"""
from __future__ import annotations

from aiogram.types import Message

import config
from utils import editorial_channel as editorial
from utils import editorial_overrides as overrides

MAX_DOMAINS_PER_SEARCH = 8

# IMPORTANT: Anthropic rejects the entire request when even one allowed domain
# is inaccessible to its user agent. nu.nl is confirmed inaccessible from the
# Railway production log (25-08-2026), so it must not be present here.
EVENING_SOURCE_GROUPS = (
    ["canonvannederland.nl", "rijksmuseum.nl", "openluchtmuseum.nl", "cultureelerfgoed.nl", "stadsarchief.amsterdam.nl", "archieven.nl"],
    ["holland.com", "iamsterdam.com", "cbs.nl", "rijksoverheid.nl", "government.nl"],
    ["nos.nl", "nltimes.nl", "dutchnews.nl", "holland.com", "iamsterdam.com"],
)


async def _robust_evening_post() -> str | None:
    recent = await editorial._recent_topics()
    system = (
        "Ты вечерний редактор Telegram-канала для русскоязычных людей, которые уже живут в Нидерландах. "
        "Нужен ОДИН готовый пост на 21:00. Разрешены только две рубрики: «История одного места/предмета» "
        "или «Почему здесь так?». Выбери один конкретный небанальный сюжет и расскажи его живо и понятно. "
        "Это не новости и не подборка. Не используй банальности про уровень моря, велосипеды, тюльпаны, "
        "кофешопы, красные фонари, мельницы, деревянные башмаки и прямолинейность голландцев. "
        "Факты проверь веб-поиском. Не описывай процесс поиска, не пиши «я выбрал», «нашёл материал», "
        "«проверил источники». Возвращай ТОЛЬКО текст готовой публикации. 550–780 знаков, без markdown и HTML."
    )
    user = (
        f"Сегодня {editorial._now():%d.%m.%Y}. Не повторяй последние темы: "
        f"{', '.join(recent) or 'нет'}. Сразу выдай готовый пост."
    )

    for domains in EVENING_SOURCE_GROUPS:
        try:
            result = await editorial._generate(system, user, domains[:MAX_DOMAINS_PER_SEARCH], 850)
        except Exception as exc:  # noqa: BLE001
            editorial.log.warning("Evening source group failed: %s", exc)
            continue
        if result and result[0] and len(result[0].strip()) >= 220:
            return result[0].strip()
    return None


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
    """Replace the already-registered /editorialhealth callback in overrides.router."""
    try:
        for handler in overrides.router.message.handlers:
            callback = getattr(handler, "callback", None)
            if getattr(callback, "__name__", "") == "editorial_health_command":
                handler.callback = editorial_health_real
                return
    except Exception as exc:  # noqa: BLE001
        editorial.log.warning("Could not replace editorial health handler: %s", exc)


def install_editorial_websearch_fix() -> None:
    overrides._focused_evening_post = _robust_evening_post
    editorial._evening_post = _robust_evening_post
    _replace_health_handler()


# bot.py imports handlers before it imports install() from editorial_overrides.
# Wrap that install function now, so our fix is re-applied AFTER the original
# override installation and cannot be overwritten during startup.
_original_install = overrides.install


def _wrapped_install() -> None:
    _original_install()
    install_editorial_websearch_fix()


overrides.install = _wrapped_install
