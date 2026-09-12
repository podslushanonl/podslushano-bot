"""Публикация гайда «Налоги и субсидии Нидерланды 2026» в Telegram-канале."""
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from database.db import get_session
from database.models import Meta

log = logging.getLogger(__name__)
router = Router()

TAX_COVER_KEY = "tax_guide_2026_cover_file_id"
TAX_PDF_KEY = "tax_guide_2026_pdf_file_id"
INSTAGRAM_URL = "https://www.instagram.com/podslushano.nl?igsh=NXhqeG56bmYxa21z&utm_source=qr"
TIKKIE_URL = "https://tikkie.me/pay/bdq116u14estu9nhp9jo"

TAX_POST_TEXT = (
    "<b>Налоги и субсидии в Нидерландах — разбор на 2026 год 🇳🇱</b>\n\n"
    "Налоги и субсидии здесь тесно связаны: с одной стороны, вы платите государству, "
    "с другой — государство может платить вам. И именно в этой системе легко что-то "
    "упустить, переплатить или неожиданно получить требование вернуть деньги.\n\n"
    "Мы собрали большой разбор и постарались объяснить всё простым языком: DigiD и ведомства, "
    "zorgtoeslag, huurtoeslag, выплаты на детей, три box, налоговые скидки, декларация, "
    "нюансы для ZZP и наёмных работников и частые ошибки, на которых теряют деньги.\n\n"
    "Все суммы и пороги в гайде — на 2026 год и сверены с официальными источниками. "
    "Это информационный разбор, а не индивидуальная налоговая консультация.\n\n"
    "Гайд можно скачать бесплатно по кнопке ниже 👇\n\n"
    "Если такие разборы вам полезны, их можно поддержать — это помогает нам делать больше "
    "подобных материалов для сообщества."
)


async def _get_meta(key: str) -> str | None:
    async with get_session() as session:
        meta = await session.get(Meta, key)
    return meta.value if meta and meta.value else None


async def _set_meta(key: str, value: str) -> None:
    async with get_session() as session:
        await session.merge(Meta(key=key, value=value))
        await session.commit()


def _is_pdf(message: Message) -> bool:
    if not message.document:
        return False
    filename = (message.document.file_name or "").lower()
    mime = (message.document.mime_type or "").lower()
    return filename.endswith(".pdf") or mime == "application/pdf"


def _final_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📚 Ещё разборы", url=INSTAGRAM_URL),
            InlineKeyboardButton(text="❤️ Поддержать разборы", url=TIKKIE_URL),
        ],
        [
            InlineKeyboardButton(
                text="📥 Скачать гайд",
                url=f"https://t.me/{bot_username}?start=tax_guide_2026",
            )
        ],
    ])


def _preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опубликовать пост", callback_data="publish_tax_guide_confirm")
    ]])


async def _save_pdf_and_cover(message: Message) -> tuple[str | None, str | None]:
    """Сохраняет PDF и, если Telegram дал thumbnail, использует его как обложку поста."""
    if not _is_pdf(message):
        return None, None
    pdf_file_id = message.document.file_id
    await _set_meta(TAX_PDF_KEY, pdf_file_id)
    cover_file_id = None
    thumb = getattr(message.document, "thumbnail", None) or getattr(message.document, "thumb", None)
    if thumb:
        cover_file_id = thumb.file_id
        await _set_meta(TAX_COVER_KEY, cover_file_id)
    return pdf_file_id, cover_file_id


@router.message(Command("set_tax_guide_cover"))
async def set_tax_guide_cover(message: Message) -> None:
    if message.from_user is None or message.from_user.id not in config.ADMIN_IDS:
        return
    if not message.photo:
        await message.answer("Отправьте фото с подписью <code>/set_tax_guide_cover</code>.")
        return
    await _set_meta(TAX_COVER_KEY, message.photo[-1].file_id)
    await message.answer("✅ Фото для поста сохранено.")


@router.message(Command("set_tax_guide_pdf"))
async def set_tax_guide_pdf(message: Message) -> None:
    if message.from_user is None or message.from_user.id not in config.ADMIN_IDS:
        return
    pdf_file_id, cover_file_id = await _save_pdf_and_cover(message)
    if not pdf_file_id:
        await message.answer("Отправьте PDF с подписью <code>/set_tax_guide_pdf</code>.")
        return
    if cover_file_id:
        await message.answer("✅ PDF сохранён. Обложку бот взял из первой страницы файла.")
    else:
        await message.answer(
            "✅ PDF сохранён. Telegram не передал превью первой страницы — отправьте фото с подписью "
            "<code>/set_tax_guide_cover</code>."
        )


@router.message(CommandStart(deep_link=True), F.text.endswith(" tax_guide_2026"))
async def download_tax_guide(message: Message) -> None:
    pdf_file_id = await _get_meta(TAX_PDF_KEY)
    if not pdf_file_id:
        await message.answer("Гайд временно недоступен. Попробуйте немного позже.")
        return
    await message.answer_document(
        pdf_file_id,
        caption="<b>Налоги и субсидии в Нидерландах · 2026</b>\n\nСохраните файл, чтобы он был под рукой.",
    )


@router.message(Command("publish_tax_guide"))
async def preview_tax_guide(message: Message) -> None:
    """PDF можно отправить прямо с командой — бот сам сохранит файл и возьмёт thumbnail."""
    if message.from_user is None or message.from_user.id not in config.ADMIN_IDS:
        return

    if message.document:
        pdf_file_id, auto_cover = await _save_pdf_and_cover(message)
        if not pdf_file_id:
            await message.answer("Для этой команды нужен PDF-файл.")
            return
        if auto_cover:
            await message.answer("✅ PDF и обложка подготовлены из одного файла.")

    cover_file_id = await _get_meta(TAX_COVER_KEY)
    pdf_file_id = await _get_meta(TAX_PDF_KEY)
    missing = []
    if not pdf_file_id:
        missing.append("отправьте сам PDF с подписью /publish_tax_guide")
    if not cover_file_id:
        missing.append("отправьте фото с подписью /set_tax_guide_cover")
    if missing:
        await message.answer("Сначала нужно:\n• " + "\n• ".join(missing))
        return

    await message.answer_photo(
        cover_file_id,
        caption="<b>Предпросмотр публикации:</b>\n\n" + TAX_POST_TEXT,
        reply_markup=_preview_keyboard(),
    )


@router.callback_query(F.data == "publish_tax_guide_confirm")
async def publish_tax_guide_confirm(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Только для администраторов", show_alert=True)
        return
    channel = config.ANNOUNCE_CHANNEL
    if not channel:
        await callback.answer("Не задан ANNOUNCE_CHANNEL", show_alert=True)
        return
    cover_file_id = await _get_meta(TAX_COVER_KEY)
    pdf_file_id = await _get_meta(TAX_PDF_KEY)
    if not cover_file_id or not pdf_file_id:
        await callback.answer("Не настроены фото или PDF", show_alert=True)
        return
    try:
        me = await callback.bot.me()
        await callback.bot.send_photo(
            channel,
            cover_file_id,
            caption=TAX_POST_TEXT,
            reply_markup=_final_keyboard(me.username),
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Не удалось опубликовать налоговый гайд")
        await callback.answer("Ошибка публикации", show_alert=True)
        await callback.message.answer(f"❌ Не удалось опубликовать: {html.escape(str(exc))}")
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("✅ Пост опубликован одним сообщением: фото + текст + 3 кнопки.")
    await callback.answer("Опубликовано")
