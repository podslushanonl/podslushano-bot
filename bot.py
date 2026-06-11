"""Точка входа: запуск бота. Запускается командой:  python bot.py"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
from database.db import init_db
from handlers import contacts, moderation, start, submissions


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config.validate()  # упадём с понятной ошибкой, если не настроен .env

    await init_db()  # создаём таблицы и заливаем примеры специалистов

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Порядок важен: сначала /start и «Отмена», потом остальное
    dp.include_router(start.router)
    dp.include_router(submissions.router)
    dp.include_router(contacts.router)
    dp.include_router(moderation.router)

    logging.info("Бот запущен. Останови через Ctrl+C.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
