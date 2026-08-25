"""Hardening for editorial Anthropic Web Search.

The evening source list is larger than a safe server-tool whitelist.  This
module avoids passing the whole list at once, retries with smaller source
families, and exposes a real Anthropic+WebSearch health check.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import config
from utils import editorial_channel as editorial
from utils import editorial_overrides as overrides

router = Router()

# Keep every web-search request comfortably below provider whitelist limits.
MAX_DOMAINS_PER_SEARCH = 8

EVENING_SOURCE_GROUPS = (
    ["canonvannederland.nl", "rijksmuseum.nl", "openluchtmuseum.nl", "cultureelerfgoed.nl", "stadsarchief.amsterdam.nl", "archieven.nl"],
    ["holland.com", "iamsterdam.com", "cbs.nl", "rijksoverheid.nl", "government.nl"],
    ["nos.nl", "nu.nl", "nltimes.nl", "dutchnews.nl", "holland.com", "iamsterdam.com"],
)


async def _robust_evening_post() -> str | None:
    """Generate the evening post through several small, valid web-search batches."""
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

    # One bad source/domain must not kill the whole 21:00 slot.
    for domains in EVENING_SOURCE_GROUPS:
        result = await editorial._generate(system, user, domains[:MAX_DOMAINS_PER_SEARCH], 850)
        if result and result[0] and len(result[0].strip()) >= 220:
            return result[0].strip()
    return None


async def _real_web_health() -> tuple[bool, str]:
    """Actually execute the same Anthropic server web-search path used by posts."""
    if not config.ANTHROPIC_API_KEY:
        return False, "ANTHROPIC_API_KEY отсутствует"
    if not config.AI_WEB_SEARCH:
        return False, "AI_WEB_SEARCH выключен"
    try:
        result = await editorial._generate(
            "Проверь веб-поиском текущую официальную страницу KNMI. Ответь одним коротким предложением по-русски. Без markdown.",
            "Нужно выполнить реальный тест веб-поиска. Не отвечай из памяти.",
            ["knmi.nl"],
            180,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"реальный запрос упал: {type(exc).__name__}: {exc}"
    if not result or not result[0]:
        return False, "реальный Web Search вернул пустой/непроверенный результат"
    return True, "реальный Anthropic Web Search успешно вернул проверенный текст"


@router.message(Command("editorialhealth"))
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


def install_editorial_websearch_fix() -> None:
    # Both scheduled and manual evening previews use this function after startup.
    overrides._focused_evening_post = _robust_evening_post
    editorial._evening_post = _robust_evening_post
