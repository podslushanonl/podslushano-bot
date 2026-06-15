"""Точка входа: запуск бота. Запускается командой:  python bot.py"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeChat

import config
from database.db import init_db
from handlers import (
    admin, afisha, board, chat, contacts, errors, events, guides, letters, moderation,
    salary, selfadd, share, start, submissions, support,
)
from handlers.selfadd import reminder_loop
from utils.limits import ThrottleMiddleware
from utils.users import RegisterUserMiddleware
from utils.webserver import start_webserver


async def configure_profile(bot: Bot) -> None:
    """Настраивает «витрину» бота: команды, краткое и полное описание.

    Полное описание показывается на стартовом экране (пустой чат, кнопка
    «Что может делать этот бот / Запустить»). Меняется при каждом запуске,
    поэтому всегда актуально.
    """
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Запустить бота и открыть меню"),
                BotCommand(command="menu", description="Показать меню"),
                BotCommand(command="help", description="Что я умею"),
                BotCommand(command="guide", description="Полезное о жизни в Нидерландах"),
                BotCommand(command="afisha", description="Чем заняться: афиша и идеи 🎉"),
                BotCommand(command="afisha_add", description="Разместить мероприятие в афише 📅"),
                BotCommand(command="board", description="Доска объявлений 📋"),
                BotCommand(command="letter", description="Разобрать письмо по фото"),
                BotCommand(command="salary", description="Калькулятор netto-зарплаты"),
                BotCommand(command="share", description="Поделиться ботом с друзьями"),
                BotCommand(command="contact", description="Связаться с нами / поддержка"),
                BotCommand(command="report", description="Сообщить об ошибке 🐞"),
                BotCommand(command="privacy", description="Конфиденциальность и условия"),
            ]
        )
        await bot.set_my_short_description(
            "Помощник сообщества «Подслушано в Нидерландах»: ответы о жизни в NL, "
            "поиск специалистов, истории и вопросы."
        )
        await bot.set_my_description(
            "«Подслушано в Нидерландах» 🇳🇱 — бот-помощник для русскоязычных "
            "жителей Нидерландов.\n\n"
            "Что я умею:\n"
            "• Отвечаю на вопросы о жизни в NL: BSN, DigiD, налоги, жильё, медицина, транспорт\n"
            "• Найду специалиста из проверенного гайда\n"
            "• Приму историю, вопрос, видео или заявку на рекламу\n\n"
            f"Сайт сообщества: {config.SITE_URL}\n\n"
            "Нажми «Запустить», чтобы начать 👇"
        )
        # Для админов в меню добавляем команду /admin
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.set_my_commands(
                    [
                        BotCommand(command="start", description="Запустить бота и открыть меню"),
                        BotCommand(command="menu", description="Показать меню"),
                        BotCommand(command="contact", description="Связаться с нами / поддержка"),
                        BotCommand(command="admin", description="Управление базой (админ)"),
                        BotCommand(command="broadcast", description="Рассылка-анонс (админ)"),
                        BotCommand(command="announce", description="Пост в канал с кнопкой (админ)"),
                        BotCommand(command="afishapost", description="Афиша «Чем заняться» в канал (админ)"),
                        BotCommand(command="afisha_new", description="Добавить в афишу вручную (админ)"),
                        BotCommand(command="afisha_export", description="Собрать афишу месяца для IG (админ)"),
                        BotCommand(command="stats", description="Статистика (админ)"),
                        BotCommand(command="reviews", description="Последние отзывы (админ)"),
                    ],
                    scope=BotCommandScopeChat(chat_id=admin_id),
                )
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001 — витрина не критична для работы
        logging.warning("Не удалось настроить профиль бота: %s", e)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config.validate()  # упадём с понятной ошибкой, если не настроен .env

    await init_db()  # создаём таблицы и заливаем примеры специалистов

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.message.middleware(ThrottleMiddleware())  # антиспам по частоте сообщений
    dp.message.middleware(RegisterUserMiddleware())  # учёт пользователей для рассылок
    dp.callback_query.middleware(RegisterUserMiddleware())

    await configure_profile(bot)  # описание/команды на стартовом экране

    # Порядок важен: сначала команды и кнопки меню, СВОБОДНЫЙ ЧАТ — последним,
    # чтобы он ловил только то, что не поймали остальные
    dp.include_router(start.router)
    dp.include_router(guides.router)  # 📚 Полезное — справочник о жизни в NL
    dp.include_router(events.router)  # ☀️ Чем заняться — афиша и сезонные идеи
    dp.include_router(letters.router)  # 📩 разбор официальных писем по фото
    dp.include_router(salary.router)  # 🧮 калькулятор netto-зарплаты
    dp.include_router(share.router)  # 📣 поделиться ботом / рефералы
    dp.include_router(support.router)  # связь с командой / возвраты
    dp.include_router(admin.router)  # /admin — управление базой (только админы)
    dp.include_router(board.router)  # 📋 доска объявлений
    dp.include_router(afisha.router)  # 📅 платная «Афиша месяца» (мероприятия)
    dp.include_router(selfadd.router)  # платное само-добавление в гайд
    dp.include_router(submissions.router)
    dp.include_router(contacts.router)
    dp.include_router(moderation.router)
    dp.include_router(chat.router)
    dp.include_router(errors.router)  # глобальный перехват ошибок (краш-репорт)
    # В группах/обсуждениях бот молчит: все хендлеры выше работают только
    # в личных чатах (router.message.filter PRIVATE), а группового нет.

    # Веб-сервер (webhook оплаты + health-check) и фоновые напоминания
    try:
        await start_webserver(bot)
        asyncio.create_task(reminder_loop(bot))
    except Exception as e:  # noqa: BLE001 — без веб-сервера бот всё равно работает
        logging.warning("Веб-сервер не запустился: %s", e)

    logging.info("Бот запущен. Останови через Ctrl+C.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
