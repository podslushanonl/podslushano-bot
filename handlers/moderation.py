"""Обработка кнопок модерации в личке у админов."""
from aiogram import F, Router
from aiogram.types import CallbackQuery

import config
from database.db import get_session
from database.models import Submission

router = Router()

# Что показываем пользователю, когда его заявку одобрили/отклонили
USER_APPROVED = {
    "story": "Твоя история одобрена и скоро появится в нашем Instagram! 🎉",
    "question": "Твой вопрос принят — скоро ответим 🙌",
    "video": "Твоё видео одобрено, спасибо! 🎬",
    "ad": "Спасибо за заявку! Мы свяжемся с тобой по поводу сотрудничества 📢",
}
USER_REJECTED = "Спасибо за заявку! К сожалению, в этот раз мы её не опубликуем 🙏"


async def _update_status(submission_id: int, status: str) -> Submission | None:
    async with get_session() as session:
        submission = await session.get(Submission, submission_id)
        if submission is None:
            return None
        submission.status = status
        await session.commit()
        await session.refresh(submission)
        return submission


@router.callback_query(F.data.startswith("approve:"))
async def approve(callback: CallbackQuery) -> None:
    await _handle(callback, "approved")


@router.callback_query(F.data.startswith("reject:"))
async def reject(callback: CallbackQuery) -> None:
    await _handle(callback, "rejected")


async def _handle(callback: CallbackQuery, status: str) -> None:
    # На всякий случай проверяем, что нажал именно админ
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("Только для администраторов", show_alert=True)
        return

    submission_id = int(callback.data.split(":", 1)[1])
    submission = await _update_status(submission_id, status)

    if submission is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    admin = f"@{callback.from_user.username}" if callback.from_user.username else "админ"
    mark = "✅ ОДОБРЕНО" if status == "approved" else "❌ ОТКЛОНЕНО"
    note = f"\n\n— {mark} ({admin})"

    # Дописываем отметку к сообщению и убираем кнопки
    if callback.message.text:
        await callback.message.edit_text(callback.message.text + note, reply_markup=None)
    elif callback.message.caption:
        await callback.message.edit_caption(
            caption=callback.message.caption + note, reply_markup=None
        )
    else:
        await callback.message.edit_reply_markup(reply_markup=None)

    # Сообщаем пользователю результат
    try:
        if status == "approved":
            text = USER_APPROVED.get(submission.type, "Твоя заявка одобрена! 🎉")
        else:
            text = USER_REJECTED
        await callback.bot.send_message(submission.user_id, text)
    except Exception as e:  # noqa: BLE001 — пользователь мог заблокировать бота
        print(f"Не удалось уведомить пользователя {submission.user_id}: {e}")

    await callback.answer("Готово")
