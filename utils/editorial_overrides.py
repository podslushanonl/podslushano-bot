"""Focused evening themes, on-demand previews and robust photo-required publishing."""
from __future__ import annotations

import os
import uuid

import aiohttp
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from utils import editorial_channel as editorial
from utils.editorial_media import choose_editorial_image

router = Router()


REACTION_CTA = {
    "morning": (
        "Если такой утренний бриф полезен — оставьте ❤️",
        "Хотите видеть такие сводки каждое утро — 🔥",
        "Если это экономит вам время утром — ❤️",
    ),
    "event": (
        "Пошли бы на такое? Оставьте 🔥",
        "Если забираете событие себе в планы — ❤️",
        "Если хотите больше таких находок — 🔥",
    ),
    "curiosity": (
        "Если было интересно — оставьте ❤️",
        "Если хотите больше таких историй — 🔥",
        "Если узнали что-то новое — ❤️",
    ),
    "evening": (
        "Если любите такие истории про Нидерланды — ❤️",
        "Если продолжать эту рубрику — 🔥",
        "Если было интересно дочитать до конца — ❤️",
    ),
}


async def _focused_evening_post() -> str | None:
    recent = await editorial._recent_topics()
    system = (
        "Ты вечерний редактор Telegram-канала для русскоязычных людей, которые уже живут в Нидерландах. "
        "В 21:00 выходит один живой пост. Разрешены ТОЛЬКО две рубрики, их нужно чередовать по смыслу: "
        "1) «История одного места/предмета» — конкретное место, здание, улица, сооружение, предмет, знак, "
        "элемент городской среды или повседневная вещь в Нидерландах и неожиданная проверяемая история; "
        "2) «Почему здесь так?» — конкретная деталь повседневной жизни, которую замечают, но редко понимают. "
        "Это НЕ новости и НЕ подборка. Не используй банальности про уровень моря, велосипеды, тюльпаны, "
        "кофешопы, красные фонари, мельницы, деревянные башмаки и прямолинейность голландцев. "
        "Не начинай с «А вы знали?». Факты обязательно проверяй веб-поиском. 500-760 знаков. "
        "Человеческий русский язык, без маркетингового CTA, markdown и HTML."
    )
    result = await editorial._generate(
        system,
        f"Сегодня {editorial._now():%d.%m.%Y}. Не повторяй последние темы: {', '.join(recent) or 'нет'}.",
        editorial.EVENING_SOURCES,
        800,
    )
    return result[0] if result else None


def _reaction_cta(kind: str, text: str) -> str:
    variants = REACTION_CTA.get(kind) or REACTION_CTA["curiosity"]
    index = sum(ord(ch) for ch in text[:240]) % len(variants)
    return variants[index]


def _with_reaction_cta(kind: str, text: str) -> str:
    clean = text.rstrip()
    return f"{clean}\n\n{_reaction_cta(kind, clean)}"


def _caption(text: str, attribution: str = "") -> str:
    suffix = f"\n\n{attribution}" if attribution else ""
    limit = 1020 - len(suffix)
    if len(text) <= limit:
        return text + suffix
    parts = text.rsplit("\n\n", 1)
    if len(parts) == 2 and parts[1].strip().endswith(("❤️", "🔥")):
        body, cta = parts
        body_limit = max(120, limit - len(cta) - 2)
        clipped = body[:body_limit].rstrip()
        boundary = max(clipped.rfind("\n\n"), clipped.rfind(". "), clipped.rfind("! "), clipped.rfind("? "))
        if boundary > int(body_limit * 0.72):
            clipped = clipped[:boundary + 1].rstrip()
        return f"{clipped}\n\n{cta}" + suffix
    return text[:limit].rstrip() + suffix


def _new_draft_id() -> str:
    # Старый ID строился из timestamp и мог столкнуться при двух запросах в одну секунду.
    return uuid.uuid4().hex[:12]


def _retry_photo_kb(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Создать фото ещё раз", callback_data=f"edretry:{draft_id}")],
        [InlineKeyboardButton(text="❌ Пропустить", callback_data=f"edskip:{draft_id}")],
    ])


def _image_failure_reason(kind: str) -> str:
    if kind in {"morning", "evening"} and not os.getenv("OPENAI_API_KEY", "").strip():
        return "OPENAI_API_KEY не задан в окружении Railway."
    if kind in {"morning", "evening"}:
        return "Ключ найден, но Images API не вернул изображение. Проверьте /editorialhealth."
    return "Не найдено подходящее реальное фото и AI-генерация также не сработала."


async def _send_photo_preview(bot, admin_id: int, draft_id: str, kind: str, text: str, button: bool, image) -> bool:
    labels = {
        "morning": "Утренний бриф",
        "event": "Мероприятие",
        "curiosity": "Познавательный пост",
        "evening": "Вечерний пост",
    }
    header = f"👀 {labels.get(kind, kind)}. Предпросмотр\n\n"
    footer = "\n\nВ канал ничего не уйдёт, пока вы не подтвердите публикацию."
    msg = await bot.send_photo(
        admin_id,
        photo=image.photo,
        caption=_caption(header + text + footer, image.attribution),
        parse_mode=None,
        reply_markup=editorial._approval_kb(draft_id),
    )
    if not msg.photo:
        return False
    await editorial._meta_set(f"ed_{draft_id}_photo", msg.photo[-1].file_id)
    await editorial._meta_set(f"ed_{draft_id}_credit", image.attribution[:95])
    await editorial._meta_set(f"ed_{draft_id}_image_status", "ready")
    return True


async def _photo_send_for_approval(bot, kind: str, text: str, button: bool = False) -> bool:
    """Текст черновика сохраняется всегда; фото можно повторить без повторной генерации текста."""
    draft_id = _new_draft_id()
    post_text = _with_reaction_cta(kind, text)
    await editorial._store_draft(draft_id, kind, post_text, button)
    await editorial._meta_set(f"ed_{draft_id}_image_status", "generating")

    image = await choose_editorial_image(text, kind)
    sent = False
    if image:
        for admin_id in config.ADMIN_IDS:
            try:
                sent = await _send_photo_preview(bot, admin_id, draft_id, kind, post_text, button, image) or sent
            except Exception as exc:  # noqa: BLE001
                editorial.log.warning("Cannot send photo preview: %s", exc)
        if sent:
            return True

    await editorial._meta_set(f"ed_{draft_id}_image_status", "failed")
    reason = _image_failure_reason(kind)
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                "⚠️ <b>Текст поста готов, но фото не создано.</b>\n\n"
                f"{post_text}\n\n"
                f"<b>Диагностика:</b> {reason}\n\n"
                "Текст сохранён. Можно повторить только создание фотографии — заново искать тему и писать пост не нужно.",
                reply_markup=_retry_photo_kb(draft_id),
                disable_web_page_preview=True,
            )
            sent = True
        except Exception as exc:  # noqa: BLE001
            editorial.log.warning("Cannot send failed-image draft preview: %s", exc)
    return sent


async def _publish_media_draft(callback: CallbackQuery) -> None:
    draft_id = callback.data.split(":", 1)[1]
    draft = await editorial._load_draft(draft_id)
    if not draft:
        await callback.answer("Этот черновик уже обработан", show_alert=True)
        return
    kind, text, button = draft
    photo_file_id = await editorial._meta_get(f"ed_{draft_id}_photo")
    credit = await editorial._meta_get(f"ed_{draft_id}_credit")
    if not photo_file_id:
        await callback.answer("Фото ещё не готово. Сначала нажмите «Создать фото ещё раз».", show_alert=True)
        return
    try:
        await callback.bot.send_photo(
            config.ANNOUNCE_CHANNEL,
            photo=photo_file_id,
            caption=_caption(text, credit),
            parse_mode=None,
            reply_markup=editorial._channel_kb() if button else None,
        )
        if kind in {"event", "curiosity", "evening"}:
            await editorial._remember_topic(text)
        await editorial._meta_set(f"ed_{draft_id}_status", "published")
        await callback.answer("Опубликовано")
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as exc:  # noqa: BLE001
        editorial.log.warning("Editorial photo publish failed: %s", exc)
        await callback.answer("Не удалось опубликовать", show_alert=True)


async def _check_openai_image_access() -> tuple[bool, str]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return False, "OPENAI_API_KEY отсутствует"
    model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1.5").strip() or "gpt-image-1.5"
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"https://api.openai.com/v1/models/{model}",
                headers={"Authorization": f"Bearer {key}"},
            ) as response:
                if response.status == 200:
                    return True, f"доступ к {model} подтверждён"
                body = (await response.text())[:180].replace("\n", " ")
                return False, f"HTTP {response.status}: {body}"
    except Exception as exc:  # noqa: BLE001
        return False, f"ошибка соединения: {type(exc).__name__}: {exc}"


async def _channel_health(bot) -> tuple[bool, str]:
    if not config.ANNOUNCE_CHANNEL:
        return False, "ANNOUNCE_CHANNEL не задан"
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(config.ANNOUNCE_CHANNEL, me.id)
        status = str(member.status)
        can_post = bool(getattr(member, "can_post_messages", False)) or "administrator" in status
        return can_post, f"{config.ANNOUNCE_CHANNEL}; статус бота: {status}"
    except Exception as exc:  # noqa: BLE001
        return False, f"не удалось проверить канал: {type(exc).__name__}: {exc}"


def install() -> None:
    editorial._evening_post = _focused_evening_post
    editorial._send_for_approval = _photo_send_for_approval


def _preview_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌦 Утренний бриф", callback_data="edtest:morning")],
        [InlineKeyboardButton(text="🎭 Мероприятие", callback_data="edtest:event")],
        [InlineKeyboardButton(text="💡 Познавательный пост", callback_data="edtest:curiosity")],
        [InlineKeyboardButton(text="🌙 Вечерний пост 21:00", callback_data="edtest:evening")],
    ])


@router.message(Command("editorialpreview"))
async def editorial_preview_command(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await message.answer(
        "👀 <b>Предпросмотр следующих редакционных постов</b>\n\n"
        "Выберите формат. Бот подготовит текст и фотографию. Если фото-сервис недоступен, "
        "текст не потеряется: черновик сохранится и появится кнопка повторной генерации фото.",
        reply_markup=_preview_menu(),
    )


@router.message(Command("editorialhealth"))
async def editorial_health_command(message: Message) -> None:
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await message.answer("🔎 Проверяю редакционную систему…")
    openai_ok, openai_detail = await _check_openai_image_access()
    channel_ok, channel_detail = await _channel_health(message.bot)
    anthropic_ok = bool(getattr(config, "ANTHROPIC_API_KEY", ""))
    web_ok = bool(getattr(config, "AI_WEB_SEARCH", False))
    announce_ok = bool(config.ANNOUNCE_CHANNEL)
    lines = [
        "🩺 <b>Editorial Health</b>",
        "",
        f"{'✅' if anthropic_ok else '❌'} Anthropic / генерация текста: {'ключ задан' if anthropic_ok else 'ANTHROPIC_API_KEY отсутствует'}",
        f"{'✅' if web_ok else '❌'} Web Search: {'включён' if web_ok else 'выключен'}",
        f"{'✅' if openai_ok else '❌'} OpenAI Images: {openai_detail}",
        f"{'✅' if announce_ok else '❌'} ANNOUNCE_CHANNEL: {config.ANNOUNCE_CHANNEL or 'не задан'}",
        f"{'✅' if channel_ok else '❌'} Права публикации: {channel_detail}",
        f"{'✅' if config.ADMIN_IDS else '❌'} ADMIN_IDS: {len(config.ADMIN_IDS)} админ(а/ов)",
        "",
        "Если OpenAI Images отмечен ❌, утренний и вечерний посты не смогут получить динамическое фото.",
    ]
    await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("edtest:"), F.from_user.id.in_(config.ADMIN_IDS))
async def editorial_preview_callback(callback: CallbackQuery) -> None:
    kind = callback.data.split(":", 1)[1]
    generators = {
        "morning": (editorial._morning_brief, False),
        "event": (editorial._event_spotlight, True),
        "curiosity": (editorial._curiosity_post, False),
        "evening": (_focused_evening_post, False),
    }
    selected = generators.get(kind)
    if not selected:
        await callback.answer("Неизвестный формат", show_alert=True)
        return
    await callback.answer("Готовлю материал…")
    generator, button = selected
    text = await generator()
    if not text:
        await callback.message.answer(
            "❌ Не удалось получить проверенный текст. Проверьте /editorialhealth — особенно Anthropic и Web Search."
        )
        return
    await editorial._send_for_approval(callback.bot, kind, text, button)


@router.callback_query(F.data.startswith("edretry:"), F.from_user.id.in_(config.ADMIN_IDS))
async def editorial_retry_image_callback(callback: CallbackQuery) -> None:
    draft_id = callback.data.split(":", 1)[1]
    draft = await editorial._load_draft(draft_id)
    if not draft:
        await callback.answer("Черновик уже обработан или недоступен", show_alert=True)
        return
    kind, text, button = draft
    await callback.answer("Повторяю только создание фото…")
    await editorial._meta_set(f"ed_{draft_id}_image_status", "generating")
    image = await choose_editorial_image(text, kind)
    if not image:
        await editorial._meta_set(f"ed_{draft_id}_image_status", "failed")
        await callback.message.answer(
            f"❌ Фото снова не создано. {_image_failure_reason(kind)}\n\nЗапустите /editorialhealth для точной проверки."
        )
        return
    try:
        await _send_photo_preview(callback.bot, callback.from_user.id, draft_id, kind, text, button, image)
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as exc:  # noqa: BLE001
        editorial.log.warning("Retry photo preview failed: %s", exc)
        await callback.message.answer(f"❌ Фото получено, но Telegram не принял его: {type(exc).__name__}: {exc}")


@router.callback_query(F.data.startswith("edpub:"), F.from_user.id.in_(config.ADMIN_IDS))
async def editorial_photo_publish_callback(callback: CallbackQuery) -> None:
    await _publish_media_draft(callback)


@router.callback_query(F.data.startswith("edskip:"), F.from_user.id.in_(config.ADMIN_IDS))
async def editorial_photo_skip_callback(callback: CallbackQuery) -> None:
    draft_id = callback.data.split(":", 1)[1]
    if not await editorial._load_draft(draft_id):
        await callback.answer("Этот черновик уже обработан", show_alert=True)
        return
    await editorial._meta_set(f"ed_{draft_id}_status", "skipped")
    await callback.answer("Пропущено")
    await callback.message.edit_reply_markup(reply_markup=None)
