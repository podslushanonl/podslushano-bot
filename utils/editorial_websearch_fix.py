"""Hardening for the 21:00 editorial Web Search path.

The generic editorial._generate() intentionally requires citation URLs. That is
fine for source-linked formats, but Anthropic can successfully execute its
server Web Search and return a factual final answer without attaching citation
objects to the final text block. In that case HTTP is 200 and Web Search ran,
but _generate() returns None. The evening post uses a dedicated verifier: it
requires actual Web Search tool execution and no tool errors, but does not throw
away a valid final text merely because citation metadata is absent.
"""
from __future__ import annotations

import os

from aiogram.types import Message

import config
from utils import editorial_channel as editorial
from utils import editorial_overrides as overrides

PREFERRED_EVENING_SOURCES = (
    "canonvannederland.nl, rijksmuseum.nl, openluchtmuseum.nl, cultureelerfgoed.nl, "
    "stadsarchief.amsterdam.nl, archieven.nl, cbs.nl, rijksoverheid.nl, holland.com, "
    "iamsterdam.com, nos.nl"
)


def _value(obj, name: str, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _used_real_web_search(response) -> bool:
    for block in _value(response, "content", []) or []:
        btype = _value(block, "type", "")
        if btype == "web_search_tool_result":
            return True
        if btype == "server_tool_use" and _value(block, "name", "") == "web_search":
            return True
    return False


def _editorial_model() -> str:
    return os.getenv("AI_EDITORIAL_MODEL", "claude-sonnet-5").strip() or "claude-sonnet-5"


def _editorial_search_limit() -> int:
    try:
        configured = int(os.getenv("AI_EDITORIAL_WEB_MAX_USES", "2"))
    except ValueError:
        configured = 2
    return max(1, min(configured, 2))


async def _generate_evening_verified(system: str, user: str, max_tokens: int = 900) -> str | None:
    """Run real Web Search and accept final text even if citations are omitted.

    No allowed_domains whitelist is sent because one blocked site can invalidate the
    whole request. Cost is capped to at most two search uses, matching the global
    editorial budget guard.
    """
    if not editorial.ai_enabled() or not config.AI_WEB_SEARCH:
        return None
    tools = editorial._web_search_tool(None, max_uses=_editorial_search_limit())
    if not tools:
        return None
    try:
        response = await editorial._create_with_server_tool_continuation(
            editorial._get_client(),
            model=_editorial_model(),
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=tools,
        )
    except Exception as exc:  # noqa: BLE001
        editorial.log.warning("Evening verified Web Search request failed: %s", exc)
        return None

    errors = editorial._web_search_errors(response)
    if errors:
        editorial.log.warning("Evening Web Search tool errors: %s", ", ".join(errors))
        return None
    if not _used_real_web_search(response):
        editorial.log.warning("Evening response had no actual Web Search tool execution")
        return None

    text, sources = editorial._extract_text_and_sources(response)
    text = editorial._clean_text(text)
    if not text:
        editorial.log.warning("Evening Web Search succeeded but final text was empty")
        return None

    editorial.log.info(
        "Evening verified text accepted: %d chars, %d citation URL(s)",
        len(text), len(sources),
    )
    return text


async def _robust_evening_post() -> str | None:
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
        "Возвращай ТОЛЬКО готовую публикацию. 550–780 знаков, без markdown и HTML."
    )
    user = (
        f"Сегодня {editorial._now():%d.%m.%Y}. Не повторяй последние темы: "
        f"{', '.join(recent) or 'нет'}. Сразу выдай готовый пост после реального веб-поиска."
    )

    text = await _generate_evening_verified(system, user, 900)
    if text and len(text.strip()) >= 220:
        return text.strip()

    retry_user = (
        user + " Первая попытка не дала пригодного финального текста. Выбери ДРУГОЙ конкретный сюжет, "
        "снова выполни Web Search и после проверки сразу напиши публикацию."
    )
    text = await _generate_evening_verified(system, retry_user, 900)
    return text.strip() if text and len(text.strip()) >= 220 else None


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
    overrides._focused_evening_post = _robust_evening_post
    editorial._evening_post = _robust_evening_post
    _replace_health_handler()


_original_install = overrides.install


def _wrapped_install() -> None:
    _original_install()
    install_editorial_websearch_fix()


overrides.install = _wrapped_install
