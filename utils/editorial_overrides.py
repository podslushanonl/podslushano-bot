"""Focused evening themes, on-demand previews and photo-required editorial publishing."""
from __future__ import annotations

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


async def _photo_send_for_approval(bot, kind: str, text: str, button: bool = False) -> bool:
    """Редакционный draft не существует без фотографии."""
    image = await choose_editorial_image(text, kind)
    if not image:
        editorial.log.warning("Editorial draft rejected: no image found for kind=%s", kind)
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    "⚠️ Не удалось подобрать подходящее фото для редакционного поста. "
                    "Пост НЕ создан и в канал не уйдёт. Попробуйте предпросмотр ещё раз; "
                    "бот выполнит новый поиск изображения.",
                )
            except Exception:
                pass
        return False

    draft_id = f"{int(editorial._now().timestamp()) % 100000000:08d}"
    post_text = _with_reaction_cta(kind, text)
    await editorial._store_draft(draft_id, kind, post_text, button)

    labels = {
        "morning": "Утренний бриф",
        "event": "Мероприятие",
        "curiosity": "Познавательный пост",
        "evening": "Вечерний пост",
    }
    header = f"👀 {labels.get(kind, kind)}. Предпросмотр\n\n"
    footer = "\n\nВ канал ничего не уйдёт, пока вы не подтвердите публикацию."
    sent = False
    stored_file_id = ""

    for admin_id in config.ADMIN_IDS:
        try:
            msg = await bot.send_photo(
                admin_id,
                photo=stored_file_id or image.photo,
                caption=_caption(header + post_text + footer, image.attribution),
                parse_mode=None,
                reply_markup=editorial._approval_kb(draft_id),
            )
            if msg.photo:
                stored_file_id = msg.photo[-1].file_id
                await editorial._meta_set(f"ed_{draft_id}_photo", stored_file_id)
                await editorial._meta_set(f"ed_{draft_id}_credit", image.attribution[:95])
                sent = True
        except Exception as exc:  # noqa: BLE001
            editorial.log.warning("Cannot send photo preview: %s", exc)

    if not sent:
        await editorial._meta_set(f"ed_{draft_id}_status", "failed")
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
        await callback.answer("У этого черновика нет фото. Публикация заблокирована.", show_alert=True)
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
        "Выберите формат. Бот подготовит текст и ОБЯЗАТЕЛЬНО подберёт фото. "
        "Без фотографии черновик не создаётся и не может быть опубликован.",
        reply_markup=_preview_menu(),
    )


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
    await callback.answer("Готовлю текст и ищу фото…")
    generator, button = selected
    text = await generator()
    if not text:
        await callback.message.answer("Не удалось получить проверенный материал. Ничего не опубликовано.")
        return
    await editorial._send_for_approval(callback.bot, kind, text, button)


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
