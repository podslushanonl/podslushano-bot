"""Точка входа: запуск бота. Запускается командой:  python bot.py"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeChat

import config
import ad_products_runtime  # noqa: F401 — регистрирует канонические продукты /ads
import database.ad_sales_models  # noqa: F401 — регистрирует таблицы в Base.metadata
from database.db import init_db
from handlers import (
    ad_crm, ad_sales_pipeline, admin, admin_center, ads, afisha, ai_sales, allo, board, cabinet, chat,
    comment_copilot, contacts, content, digest, errors, events, guides, home, invoice_admin, letters, moderation,
    notifications, salary, selfadd, share, spotlight, start, stories, submissions, support,
    tax_guide,
)
import ad_campaign_guide_runtime  # noqa: F401 — связывает €299 с Contact Guide Premium
from handlers.ad_sales_pipeline import ad_payment_reconciliation_loop
from handlers.ai_sales import ad_lead_reminder_loop
from handlers.selfadd import reminder_loop
from handlers.digest import digest_announcement_loop, digest_draft_loop
from handlers.notifications import notification_loop
from handlers.evenementen_catalog import evenementen_catalog_loop, install_evenementen_source
from utils.editorial_channel import editorial_channel_loop, router as editorial_router
from utils.editorial_research_desk import editorial_research_loop, router as editorial_research_router
from utils.editorial_overrides import install as install_editorial_overrides, router as editorial_preview_router
from utils.limits import ThrottleMiddleware
from utils.users import RegisterUserMiddleware
from utils.ad_calendar import calendar_sync_loop
from utils.ad_reminders import ad_reminder_loop

from utils.crm_bridge import crm_sync_loop


async def configure_profile(bot: Bot) -> None:
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Запустить бота и открыть меню"),
            BotCommand(command="menu", description="Показать меню"),
            BotCommand(command="help", description="Что я умею"),
            BotCommand(command="guide", description="Полезное о жизни в Нидерландах"),
            BotCommand(command="afisha", description="Чем заняться: афиша и идеи 🎉"),
            BotCommand(command="digest", description="Настроить подборку на выходные 🔔"),
            BotCommand(command="my", description="Мой Podslushano: профиль и сохранённое"),
            BotCommand(command="notifications", description="Настроить личные уведомления"),
            BotCommand(command="afisha_add", description="Разместить мероприятие в афише 📅"),
            BotCommand(command="board", description="Доска объявлений 📋"),
            BotCommand(command="letter", description="Разобрать письмо по фото"),
            BotCommand(command="salary", description="Калькулятор netto-зарплаты"),
            BotCommand(command="share", description="Поделиться ботом с друзьями"),
            BotCommand(command="contact", description="Связаться с нами / поддержка"),
            BotCommand(command="report", description="Сообщить об ошибке 🐞"),
            BotCommand(command="privacy", description="Конфиденциальность и условия"),
        ])
        await bot.set_my_short_description("Помощник сообщества «Подслушано в Нидерландах»: ответы о жизни в NL, поиск специалистов, истории и вопросы.")
        await bot.set_my_description(
            "«Подслушано в Нидерландах» 🇳🇱 — бот-помощник для русскоязычных жителей Нидерландов.\n\n"
            "Что я умею:\n• Отвечаю на вопросы о жизни в NL: BSN, DigiD, налоги, жильё, медицина, транспорт\n"
            "• Найду специалиста из проверенного гайда\n• Приму историю, вопрос, видео или заявку на рекламу\n\n"
            f"Сайт сообщества: {config.SITE_URL}\n\nНажми «Запустить», чтобы начать 👇"
        )
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.set_my_commands([
                    BotCommand(command="start", description="Запустить бота и открыть меню"),
                    BotCommand(command="menu", description="Показать меню"),
                    BotCommand(command="admin", description="Открыть Админ-центр"),
                    BotCommand(command="contentplan", description="Контент-план канала"),
                    BotCommand(command="editorialpreview", description="Предпросмотр редакционных постов"),
                    BotCommand(command="ideas", description="Редакционный радар инфоповодов"),
                    BotCommand(command="comments", description="Ответы на комментарии"),
                    BotCommand(command="adleads", description="CRM рекламных заявок"),
                    BotCommand(command="adcalendar", description="Проверить календарь рекламы"),
                    BotCommand(command="gmailconnect", description="Подключить Gmail для материалов"),
                    BotCommand(command="invoices", description="Скачать архив фактур"),
                    BotCommand(command="contact", description="Связаться с нами / поддержка"),
                ], scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception:
                pass
    except Exception as e:
        logging.warning("Не удалось настроить профиль бота: %s", e)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Runtime подключается только при реальном запуске процесса, а не при импорте
    # bot.py в regression-тестах и служебных скриптах.
    import gmail_oauth_runtime
    import ad_material_reminder_runtime
    import ad_material_admin_gate_runtime
    import ad_material_conversation_guard  # noqa: F401 — paid-диалог только пока собираем материалы

    config.validate()
    await init_db()
    connected_gmail = await gmail_oauth_runtime.install_saved_refresh_token()
    if connected_gmail:
        logging.info("Gmail read-only подключён для рекламных материалов: %s", connected_gmail)
    install_evenementen_source()
    install_editorial_overrides()
    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.middleware(ThrottleMiddleware())
    dp.message.middleware(RegisterUserMiddleware())
    dp.callback_query.middleware(RegisterUserMiddleware())
    await configure_profile(bot)

    dp.include_router(stories.router)
    dp.include_router(tax_guide.router)
    dp.include_router(start.router)
    dp.include_router(guides.router)
    dp.include_router(events.router)
    dp.include_router(digest.router)
    dp.include_router(home.router)
    dp.include_router(notifications.router)
    dp.include_router(letters.router)
    dp.include_router(salary.router)
    dp.include_router(share.router)
    dp.include_router(support.router)
    dp.include_router(editorial_preview_router)
    dp.include_router(editorial_router)
    dp.include_router(editorial_research_router)
    dp.include_router(comment_copilot.router)
    dp.include_router(content.router)
    # Новый Админ-центр перехватывает /admin раньше старой длинной панели.
    dp.include_router(admin_center.router)
    dp.include_router(invoice_admin.router)
    dp.include_router(admin.router)
    dp.include_router(board.router)
    dp.include_router(afisha.router)
    # Gmail OAuth и напоминания о материалах доступны только администраторам.
    dp.include_router(gmail_oauth_runtime.router)
    dp.include_router(ad_material_admin_gate_runtime.router)
    dp.include_router(ad_material_reminder_runtime.router)
    dp.include_router(ads.router)
    dp.include_router(spotlight.router)
    dp.include_router(allo.router)
    dp.include_router(selfadd.router)
    dp.include_router(cabinet.router)
    dp.include_router(submissions.router)
    dp.include_router(contacts.router)
    dp.include_router(ad_crm.router)
    dp.include_router(ai_sales.router)
    dp.include_router(moderation.router)
    dp.include_router(ad_sales_pipeline.router)
    dp.include_router(chat.router)
    dp.include_router(errors.router)

    try:
        await gmail_oauth_runtime.start_webserver_with_gmail(bot)
    except Exception as e:
        logging.warning("Веб-сервер не запустился: %s", e)
    asyncio.create_task(reminder_loop(bot))
    asyncio.create_task(digest_draft_loop(bot))
    asyncio.create_task(digest_announcement_loop(bot))
    asyncio.create_task(notification_loop(bot))
    asyncio.create_task(editorial_channel_loop(bot))
    asyncio.create_task(editorial_research_loop(bot))
    asyncio.create_task(evenementen_catalog_loop(bot))
    asyncio.create_task(ad_lead_reminder_loop(bot))
    asyncio.create_task(ad_payment_reconciliation_loop(bot))
    asyncio.create_task(calendar_sync_loop(bot))
    asyncio.create_task(ad_reminder_loop(bot))

    asyncio.create_task(crm_sync_loop(bot))

    logging.info("Бот запущен. Останови через Ctrl+C.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
