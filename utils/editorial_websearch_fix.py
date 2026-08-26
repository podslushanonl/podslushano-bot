"""21:00 editorial post hardening.

The evening post must use the exact same verified Web Search generator as the
other editorial formats.  Keeping a second, evening-only Anthropic request path
caused the 21:00 slot to reject otherwise valid responses and also duplicated
search/retry spend.
"""
from __future__ import annotations

from aiogram.types import Message

import config
from utils import editorial_channel as editorial
from utils import editorial_overrides as overrides

PREFERRED_EVENING_SOURCES = (
    "canonvannederland.nl, rijksmuseum.nl, openluchtmuseum.nl, cultureelerfgoed.nl, "
    "stadsarchief.amsterdam.nl, archieven.nl, cbs.nl, rijksoverheid.nl, holland.com, "
    "iamsterdam.com, nos.nl"
)


async def _robust_evening_post() -> str | None:
    """Generate one evening post through the shared verified pipeline.

    editorial._generate is deliberately resolved at call time.  The final
    runtime installer replaces it with editorial_verified_search._verified_generate,
    so evening, morning, event and curiosity all use one implementation and one
    cost ceiling.
    """
    recent = await editorial._recent_topics()
    system = (
        "Ты вечерний редактор Telegram-канала для русскоязычных людей, которые уже живут в Нидерландах. "
        "Нужен ОДИН готовый пост на 21:00. Разрешены только две рубрики: «История одного места/предмета» "
        "или «Почему здесь так?». Выбери один конкретный небанальный сюжет и расскажи его живо и понятно. "
        "Это не новости и не подборка. Не используй банальности про уровень моря, велосипеды, тюльпаны, "
        "кофешопы, красные фонари, мельницы, деревянные башмаки и прямолинейность голландцев. "
        "ОБЯЗАТЕЛЬНО выполни Web Search перед ответом и проверь ключевые факты минимум по одному надёжному "
        "нидерландскому источнику. В приоритете: " + PREFERRED_EVENING_SOURCES + ". "
        "Не описывай процесс поиска, не пиши «я выбрал», «нашёл материал», «проверил источники». "
        "Возвращай ТОЛЬКО готовую публикацию. Текст должен быть интересным и содержательным: 650–950 знаков, "
        "один сюжет, живой человеческий язык, без markdown и HTML."
    )
    user = (
        f"Сегодня {editorial._now():%d.%m.%Y}. Не повторяй последние темы: "
        f"{', '.join(recent) or 'нет'}. Сразу выдай готовый пост после реального веб-поиска."
    )

    # IMPORTANT: no evening-only Anthropic client call and no internal retry.
    # The shared generator already verifies real Web Search and enforces the
    # configured max search uses.  This also prevents one 21:00 slot from making
    # multiple hidden paid generations.
    result = await editorial._generate(system, user, editorial.EVENING_SOURCES, 950)
    if not result:
        return None
    text = (result[0] or "").strip()
    return text if len(text) >= 220 else None


async def _real_web_health() -> tuple[bool, str]:
    if not config.ANTHROPIC_API_KEY:
        return False, "ANTHROPIC_API_KEY отсутствует"
    if not config.AI_WEB_SEARCH:
        return False, "AI_WEB_SEARCH выключен"
    try:
        result = await editorial._generate(
            "Обязательно выполни веб-поиск и ответь одним коротким предложением по-русски. Не отвечай из памяти.",
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
    overrides._focused_evening_post = _robust_evening_post
    editorial._evening_post = _robust_evening_post
    _replace_health_handler()


_original_install = overrides.install


def _wrapped_install() -> None:
    _original_install()
    install_editorial_websearch_fix()


overrides.install = _wrapped_install
