"""Точка входа: запуск бота. Запускается командой:  python bot.py"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

import config
import ad_products_runtime  # noqa: F401 — регистрирует канонические продукты /ads
import ad_season_campaign_runtime  # Q4 /ads: подписка + защищённая скидка −26%
import database.ad_sales_models  # noqa: F401 — регистрирует таблицы в Base.metadata
import database.ig_sales_models  # noqa: F401 — Instagram Direct orders / events
import instagram_sales_runtime  # noqa: F401 — Instagram Direct AI sales agent
from database.db import init_db
from handlers import (
    ad_crm, ad_sales_pipeline, admin, admin_center, ads, afisha, ai_sales, allo, anonymous_questions,
    board, cabinet, chat, comment_copilot, contacts, content, digest, errors, events, guides, home,
    invoice_admin, letters, menu, moderation, notifications, salary, selfadd, share, spotlight, start, stories,
    submissions, support, tax_guide, cabinet_web,
)
from handlers import anonymous_replies
from handlers import editorial_planner
from utils.editorial_planner import planner_reminder_loop
import ad_campaign_guide_runtime  # noqa: F401 — связывает €299 с Contact Guide Premium
import ad_ads_cleanup_runtime  # noqa: F401 — облегчённая /ads + welcome e-mail после подписки
import ad_contact_guide_web_runtime  # noqa: F401 — Contact Guide: анкета + Mollie прямо на /ads
import calendar_shop_runtime  # календарь Nederland 2027: заказ на сайте, PDF, подписка и напоминания
from handlers.ad_sales_pipeline import ad_payment_reconciliation_loop
from handlers.ai_sales import ad_lead_reminder_loop
from handlers.selfadd import reminder_loop
from handlers.digest import digest_announcement_loop, digest_draft_loop
from handlers.notifications import notification_loop
from handlers.evenementen_current_month import evenementen_catalog_loop, install_evenementen_source
from utils.editorial_channel import editorial_channel_loop, router as editorial_router
from utils.editorial_research_desk import router as editorial_research_router
from utils.editorial_research_daily import editorial_research_loop
from utils.site_guides import site_guides_loop
from utils.site_news import site_news_loop
from utils.weekly_digest import weekly_digest_loop
from utils.daily_digest import daily_digest_loop
from utils.digest_commands import router as digest_router
from utils.ns_alerts import ns_alerts_loop, router as ns_alerts_router
from utils.savings import router as savings_router, savings_loop
from utils.community import router as community_router
from utils.dm import router as dm_router
from utils.editorial_overrides import install as install_editorial_overrides, router as editorial_preview_router
from utils.limits import ThrottleMiddleware
from utils.nav_guard import NavigationGuard
from utils import inbox
from utils.users import RegisterUserMiddleware
from utils.ad_calendar import calendar_sync_loop
from utils.ad_reminders import ad_reminder_loop
from utils.allo_v2 import reconciliation_loop as allo_reconciliation_loop

from utils.crm_bridge import crm_sync_loop, router as crm_diagnostics_router


async def configure_profile(bot: Bot) -> None:
    try:
        # Пользователям — три команды, всё остальное в карточке меню. Старые команды
        # (/guide, /board, /salary…) продолжают работать, просто не висят в списке.
        user_commands = [
            BotCommand(command="start", description="Начать и открыть меню"),
            BotCommand(command="menu", description="Меню: все разделы"),
            BotCommand(command="help", description="Что я умею"),
        ]
        await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
        admin_commands = user_commands + [
            BotCommand(command="admin", description="Админ-центр: все функции кнопками"),
            BotCommand(command="inbox", description="Подключить инбокс (в группе с темами)"),
            BotCommand(command="planner", description="Открыть планировщик авторов"),
            BotCommand(command="planner_post", description="Пост с кнопкой планировщика в этом чате"),
        ]
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception as e:  # noqa: BLE001 — админ мог ещё не писать боту
                logging.info("Команды админа %s не выставлены: %s", admin_id, e)
        await bot.set_my_short_description("Помощник сообщества podslushano.nl: ответы о жизни в Нидерландах, поиск специалистов, истории и вопросы.")
        await bot.set_my_description(
            "podslushano.nl 🇳🇱 — бот-помощник для русскоязычных жителей Нидерландов.\n\n"
            "Что я умею:\n• Отвечаю на вопросы о жизни в Нидерландах: BSN, DigiD, налоги, жильё, медицина, транспорт\n"
            "• Найду специалиста из проверенного гайда\n• Афиша, объявления, поезда NS и полезные гайды\n"
            "• Приму историю, вопрос, видео или заявку на рекламу\n\n"
            f"Сайт сообщества: {config.SITE_URL}\n\nНажми «Запустить», чтобы начать 👇"
        )
    except Exception as e:
        logging.warning("Не удалось настроить профиль бота: %s", e)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Runtime подключается только при реальном запуске процесса, а не при импорте
    # bot.py в regression-тестах и служебных скриптах.
    import gmail_oauth_runtime
    import ad_material_reminder_runtime
    import ad_material_admin_gate_runtime
    import ad_material_72h_preview_runtime
    import ad_material_conversation_guard  # noqa: F401 — paid-диалог только пока собираем материалы

    import am_reviews  # register review model before init_db

    config.validate()
    await init_db()
    connected_gmail = await gmail_oauth_runtime.install_saved_refresh_token()
    if connected_gmail:
        logging.info("Gmail read-only подключён для рекламных материалов: %s", connected_gmail)
    install_evenementen_source()
    install_editorial_overrides()
    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    # Уведомления админам — в группу-инбокс с темами (если подключена командой /inbox)
    inbox.install(bot, dp)
    # Кнопки меню и /start, /menu, /help, /cancel всегда прерывают незаконченную анкету
    dp.message.outer_middleware(NavigationGuard())
    dp.message.middleware(ThrottleMiddleware())
    dp.message.middleware(RegisterUserMiddleware())
    dp.callback_query.middleware(RegisterUserMiddleware())
    await configure_profile(bot)

    dp.include_router(editorial_planner.router)
    dp.include_router(inbox.router)
    dp.include_router(am_reviews.router)
    dp.include_router(stories.router)
    dp.include_router(tax_guide.router)
    dp.include_router(cabinet_web.router)
    # ask_alex должен перехватывать только свой deep-link до общего /start.
    dp.include_router(anonymous_replies.router)
    dp.include_router(anonymous_questions.router)
    dp.include_router(ns_alerts_router)
    dp.include_router(savings_router)
    dp.include_router(community_router)
    dp.include_router(dm_router)
    dp.include_router(digest_router)
    dp.include_router(menu.router)
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
    # 72h preview должен перехватить adgate:wait до общего обработчика gate.
    dp.include_router(ad_material_72h_preview_runtime.router)
    dp.include_router(ad_material_admin_gate_runtime.router)
    dp.include_router(ad_material_reminder_runtime.router)
    dp.include_router(ads.router)
    dp.include_router(instagram_sales_runtime.router)
    dp.include_router(spotlight.router)
    dp.include_router(allo.router)
    dp.include_router(selfadd.router)
    dp.include_router(cabinet.router)
    dp.include_router(submissions.router)
    dp.include_router(contacts.router)
    dp.include_router(crm_diagnostics_router)
    dp.include_router(ad_crm.router)
    dp.include_router(ai_sales.router)
    dp.include_router(moderation.router)
    dp.include_router(ad_sales_pipeline.router)
    dp.include_router(chat.router)
    dp.include_router(errors.router)

    try:
        await ad_season_campaign_runtime.start_webserver_with_ads_campaign(bot)
    except Exception as e:
        logging.warning("Веб-сервер не запустился: %s", e)
    asyncio.create_task(reminder_loop(bot))
    asyncio.create_task(digest_draft_loop(bot))
    asyncio.create_task(digest_announcement_loop(bot))
    asyncio.create_task(notification_loop(bot))
    asyncio.create_task(editorial_channel_loop(bot))
    asyncio.create_task(editorial_research_loop(bot))
    # Автоновости на сайт: NOS → русская новость в WordPress раз в 10 минут
    asyncio.create_task(site_news_loop(bot))
    asyncio.create_task(site_guides_loop(bot))
    # Недельный дайджест в канал: пн 09:00 Амстердам
    asyncio.create_task(weekly_digest_loop(bot))
    # Ежедневный дайджест «Новости дня»: каждый день 19:00 Амстердам
    asyncio.create_task(daily_digest_loop(bot))
    from handlers.spotlight import spotlight_reminder_loop
    asyncio.create_task(spotlight_reminder_loop(bot))
    from utils.site_sync import site_sync_loop
    asyncio.create_task(site_sync_loop(bot))
    # Уведомления подписчикам о сбоях NS на их станции, раз в 5 минут, без ИИ
    asyncio.create_task(ns_alerts_loop(bot))
    asyncio.create_task(savings_loop(bot))
    asyncio.create_task(evenementen_catalog_loop(bot))
    asyncio.create_task(ad_lead_reminder_loop(bot))
    asyncio.create_task(ad_payment_reconciliation_loop(bot))
    asyncio.create_task(allo_reconciliation_loop())
    asyncio.create_task(calendar_sync_loop(bot))
    asyncio.create_task(ad_reminder_loop(bot))
    asyncio.create_task(planner_reminder_loop(bot))

    asyncio.create_task(crm_sync_loop(bot))
    asyncio.create_task(calendar_shop_runtime.calendar_loop(bot))
    asyncio.create_task(instagram_sales_runtime.worker_loop(bot))
    asyncio.create_task(instagram_sales_runtime.payment_reconciliation_loop(bot))

    logging.info("Бот запущен. Останови через Ctrl+C.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
