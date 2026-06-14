"""«Разбор письма по фото»: пользователь присылает фото официального письма,
бот объясняет по-русски (от кого, о чём, что делать, сроки).

Приватность: фото обрабатывается «на лету» и НИГДЕ не сохраняется (ни в базе,
ни в логах). Перед отправкой показываем уведомление и просьбу не присылать
чужие документы.
"""
import base64
import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards.menus import ANSWER_FOOTER, BTN_LETTER, cancel_menu, main_menu
from states.forms import LetterExplain
from utils.ai import ai_enabled, ai_explain_letter
from utils.analytics import log_event
from utils.limits import allow_ai

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

CONSENT = (
    "📩 <b>Разбор письма</b>\n\n"
    "Пришли фото официального письма (Belastingdienst, gemeente, IND, UWV, "
    "страховая, банк…) — объясню по-русски: от кого, о чём, что делать и к какому сроку.\n\n"
    "🔒 Фото обрабатываю только чтобы ответить и <b>не храню</b>. Пожалуйста, не "
    "присылай чужие документы без согласия. Это справочная помощь, не юридическая "
    "консультация."
)
CTA = (
    "\n\n💬 Нужна помощь человека? Нажми «🔍 Найти специалиста» (юрист) или /contact."
)


@router.message(Command("letter", "pismo"))
@router.message(F.text == BTN_LETTER)
async def letter_start(message: Message, state: FSMContext) -> None:
    if not ai_enabled():
        await message.answer("Разбор писем сейчас недоступен 🙏", reply_markup=main_menu())
        return
    await state.set_state(LetterExplain.waiting_photo)
    await message.answer(CONSENT, reply_markup=cancel_menu())


@router.message(LetterExplain.waiting_photo, F.photo | F.document)
async def letter_photo(message: Message, state: FSMContext) -> None:
    await state.clear()
    file_id, media = _file_from_message(message)
    if not file_id:
        await message.answer(
            "Это не похоже на фото письма 🙈 Пришли изображение (фото или скан).",
            reply_markup=main_menu(),
        )
        return
    await _explain(message, file_id, media)


@router.message(LetterExplain.waiting_photo)
async def letter_need_photo(message: Message) -> None:
    await message.answer("Пришли, пожалуйста, фото письма 📷 или нажми «❌ Отмена».")


@router.callback_query(F.data == "letter:explain")
async def letter_from_chat(callback: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Объяснить письмо» под присланным в свободном чате фото."""
    data = await state.get_data()
    await state.clear()
    file_id = data.get("chat_file_id")
    if not file_id:
        await callback.message.answer(
            "Я потерял фото 🙈 Пришли его ещё раз и нажми «Объяснить письмо».",
            reply_markup=main_menu(),
        )
        await callback.answer()
        return
    media = "image/jpeg"
    # Подтверждаем нажатие сразу: разбор письма через ИИ небыстрый, а callback
    # «живёт» ~15 сек — иначе Telegram вернёт «query is too old».
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await _explain(callback.message, file_id, media, uid=callback.from_user.id)


def _file_from_message(message: Message) -> tuple[str | None, str]:
    if message.photo:
        return message.photo[-1].file_id, "image/jpeg"
    doc = message.document
    if doc and (doc.mime_type or "").startswith("image/"):
        return doc.file_id, doc.mime_type
    return None, "image/jpeg"


async def _explain(message: Message, file_id: str, media: str, uid: int | None = None) -> None:
    uid = uid or (message.from_user.id if message.from_user else 0)
    if not allow_ai(uid):
        await message.answer(
            "На сегодня уже много запросов 🙏 Загляни попозже.", reply_markup=main_menu()
        )
        return
    await message.bot.send_chat_action(message.chat.id, action="typing")
    try:
        buf = await message.bot.download(file_id)
        image_b64 = base64.b64encode(buf.read()).decode()
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось скачать фото письма: %s", e)
        await message.answer("Не получилось загрузить фото 😔 Попробуй ещё раз.", reply_markup=main_menu())
        return
    # Явно сообщаем, что уже работаем — разбор идёт до минуты, иначе кажется, что
    # бот «завис» (индикатор «печатает…» гаснет через пару секунд).
    await message.answer("🔎 Уже разбираю письмо… Это займёт до минуты ⏳")
    await message.bot.send_chat_action(message.chat.id, action="typing")
    result = await ai_explain_letter(image_b64, media)
    if not result:
        await message.answer(
            "Не получилось разобрать 😔 Попробуй переснять чётче, при хорошем свете "
            "и чтобы весь текст был в кадре.",
            reply_markup=main_menu(),
        )
        return
    await log_event("letter", "explain")
    await message.answer(
        "📩 <b>Разбор письма</b>\n\n" + result + CTA + ANSWER_FOOTER, reply_markup=main_menu()
    )
