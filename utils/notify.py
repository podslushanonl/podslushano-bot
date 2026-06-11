"""Отправка заявок администраторам в личку."""
from aiogram import Bot

import config
from database.models import Submission
from keyboards.menus import moderation_buttons

# Человекочитаемые названия типов заявок
TYPE_TITLES = {
    "story": "📰 Новая история / сплетня",
    "question": "❓ Новый вопрос (предложка)",
    "video": "🎬 Новое видео",
    "ad": "📢 Реклама / сотрудничество",
}


def _header(submission: Submission) -> str:
    """Формирует подпись заявки для админа."""
    title = TYPE_TITLES.get(submission.type, "Новая заявка")
    author = f"@{submission.username}" if submission.username else "без username"
    lines = [
        f"<b>{title}</b>",
        f"🆔 Заявка №{submission.id}",
        f"👤 От: {author} (id {submission.user_id})",
    ]
    if submission.text:
        lines.append("")
        lines.append(submission.text)
    return "\n".join(lines)


async def send_to_admins(bot: Bot, submission: Submission) -> None:
    """Рассылает заявку всем админам из ADMIN_IDS с кнопками модерации."""
    caption = _header(submission)
    keyboard = moderation_buttons(submission.id)

    for admin_id in config.ADMIN_IDS:
        try:
            if submission.file_id and submission.file_type == "video":
                await bot.send_video(
                    admin_id, submission.file_id, caption=caption, reply_markup=keyboard
                )
            elif submission.file_id and submission.file_type == "photo":
                await bot.send_photo(
                    admin_id, submission.file_id, caption=caption, reply_markup=keyboard
                )
            elif submission.file_id and submission.file_type == "document":
                await bot.send_document(
                    admin_id, submission.file_id, caption=caption, reply_markup=keyboard
                )
            else:
                await bot.send_message(admin_id, caption, reply_markup=keyboard)
        except Exception as e:  # noqa: BLE001 — не роняем бота, если один админ недоступен
            print(f"Не удалось отправить заявку админу {admin_id}: {e}")
