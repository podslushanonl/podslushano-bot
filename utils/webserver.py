"""Маленький веб-сервер рядом с ботом — принимает webhook оплаты от Mollie.

Mollie после оплаты дёргает POST /mollie-webhook с полем id=<payment_id>.
Мы проверяем платёж и публикуем/продлеваем размещение. Также есть health-check
на GET / (нужен Railway).
"""
import logging

from aiohttp import web

import config
from database.db import get_session
from database.models import Specialist
from handlers.selfadd import on_payment_paid
from utils.payments import get_payment

log = logging.getLogger(__name__)


async def _health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#eef2f8;
  margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center}}
 .card{{background:#fff;max-width:440px;margin:20px;padding:32px 28px;border-radius:18px;
  box-shadow:0 12px 34px rgba(0,0,0,.08);text-align:center}}
 img.logo{{max-width:180px;height:auto;margin-bottom:14px}}
 .ico{{font-size:54px;line-height:1}}
 h1{{font-size:22px;margin:12px 0 6px;color:#111}}
 p{{color:#555;line-height:1.55;margin:6px 0}}
 a.btn{{display:inline-block;margin-top:22px;background:#2aabee;color:#fff;text-decoration:none;
  padding:13px 24px;border-radius:12px;font-weight:600}}
</style></head>
<body><div class="card">
 {logo}
 <div class="ico">{ico}</div>
 <h1>{title}</h1>
 {body}
 <a class="btn" href="{bot}">Вернуться в Telegram</a>
</div></body></html>"""


def _render(title: str, ico: str, body_html: str) -> str:
    logo = f'<img class="logo" src="{config.LOGO_URL}" alt="logo">' if config.LOGO_URL else ""
    return _PAGE.format(title=title, ico=ico, body=body_html, logo=logo, bot=config.BOT_URL)


_DOC_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#eef2f8;margin:0;padding:24px}}
 .wrap{{max-width:720px;margin:0 auto;background:#fff;padding:28px 30px;border-radius:16px;
  box-shadow:0 8px 24px rgba(0,0,0,.06)}}
 img.logo{{max-width:150px;margin-bottom:10px}}
 h1{{font-size:24px;margin:8px 0 4px}} h2{{font-size:18px;margin:22px 0 6px}}
 p,li{{color:#333;line-height:1.6}} .upd{{color:#888;font-size:13px;margin-bottom:10px}} a{{color:#2aabee}}
</style></head><body><div class="wrap">{logo}{body}</div></body></html>"""

_PRIVACY_BODY = """
<h1>Политика конфиденциальности</h1>
<p class="upd">Обновлено: 12.06.2026</p>
<p>Этот документ объясняет, как Telegram-бот сообщества «Подслушано в
Нидерландах» (@podslushano_nl_bot) обрабатывает ваши данные.</p>
<h2>Какие данные мы собираем</h2>
<ul>
 <li>имя/имя пользователя и ваш Telegram-ID;</li>
 <li>содержимое, которое вы отправляете (истории, вопросы, видео, заявки на
  рекламу и размещение) и ваши контактные данные;</li>
 <li>для платных размещений — данные специалиста/бизнеса и статус оплаты.
  Платежи проходят через Mollie; данные банковских карт мы не храним.</li>
</ul>
<h2>Зачем</h2>
<ul>
 <li>показ специалистов в гайде;</li>
 <li>модерация и связь с вами;</li>
 <li>обработка оплаты за размещение.</li>
</ul>
<h2>Основание обработки</h2>
<p>Ваше согласие и исполнение договора (GDPR/AVG).</p>
<h2>Передача третьим лицам</h2>
<p>Только по необходимости: Mollie (платежи), Telegram (мессенджер) и наш
хостинг (Railway, серверы в ЕС). Мы не продаём ваши данные.</p>
<h2>ИИ-ассистент</h2>
<p>Свободные вопросы могут обрабатываться сервисом ИИ (Anthropic) для
формирования ответа. Не отправляйте в чат чувствительные персональные данные.</p>
<h2>Хранение и ваши права</h2>
<p>Мы храним данные столько, сколько необходимо. Вы вправе запросить доступ,
исправление и удаление. Напишите боту или на podslushano.nl@gmail.com — и мы
удалим ваши данные.</p>
<h2>Контакты</h2>
<p>podslushano.nl@gmail.com</p>
"""

_TERMS_BODY = """
<h1>Условия размещения в гайде</h1>
<p class="upd">Обновлено: 12.06.2026</p>
<h2>Услуга</h2>
<p>Размещение вашей карточки (специалист или бизнес) в гайде «Подслушано в
Нидерландах» через Telegram-бот.</p>
<h2>Тарифы и срок</h2>
<p>Цена и период указаны в боте (месяц или год). Размещение действует выбранный
период и затем прекращается, если вы не продлите его новой оплатой. Перед
окончанием мы пришлём напоминание.</p>
<h2>Проверка</h2>
<p>Каждая заявка проверяется нами до публикации. Мы вправе отклонить или удалить
карточку — например, при неверном или неуместном содержании.</p>
<h2>Оплата</h2>
<p>Оплата проходит безопасно через Mollie (в т.ч. iDEAL).</p>
<h2>Право на отказ и возвраты</h2>
<p>У бизнес-клиентов нет законного «права на отказ». У потребителей есть 14 дней
на отказ; соглашаясь и запуская услугу сразу, вы даёте согласие на немедленное
исполнение. Если заявку отклонили — мы возвращаем сумму; напишите на
podslushano.nl@gmail.com.</p>
<h2>Ответственность</h2>
<p>Рекламодатель отвечает за достоверность предоставленных данных. Гайд носит
информационный характер; мы не являемся стороной договорённостей между
пользователями и специалистами.</p>
<h2>Применимое право</h2>
<p>К настоящим условиям применяется право Нидерландов.</p>
<h2>Контакты</h2>
<p>podslushano.nl@gmail.com</p>
"""


def _doc(title: str, body: str) -> str:
    logo = f'<img class="logo" src="{config.LOGO_URL}" alt="logo">' if config.LOGO_URL else ""
    return _DOC_PAGE.format(title=title, logo=logo, body=body)


async def _privacy(request: web.Request) -> web.Response:
    return web.Response(
        text=_doc("Политика конфиденциальности", _PRIVACY_BODY), content_type="text/html"
    )


async def _terms(request: web.Request) -> web.Response:
    return web.Response(
        text=_doc("Условия размещения", _TERMS_BODY), content_type="text/html"
    )


async def _thanks(request: web.Request) -> web.Response:
    """Страница после оплаты: показывает реальный статус платежа."""
    title, ico, body = (
        "Спасибо!",
        "🙌",
        "<p>Мы обрабатываем ваш платёж. Статус придёт вам в Telegram.</p>",
    )
    sid = request.query.get("sid")
    if sid and sid.isdigit():
        try:
            async with get_session() as session:
                sp = await session.get(Specialist, int(sid))
            payment = await get_payment(sp.payment_id) if sp and sp.payment_id else None
            status = (payment or {}).get("status")
            if status == "paid":
                title, ico = "Оплата прошла успешно!", "✅"
                body = (
                    "<p>Спасибо! Ваша анкета отправлена на проверку.</p>"
                    "<p>Как только мы её одобрим, карточка появится в гайде — "
                    "бот напишет вам в Telegram.</p>"
                )
            elif status in ("failed", "canceled", "expired"):
                title, ico = "Оплата не завершена", "⚠️"
                body = (
                    "<p>Похоже, оплата не прошла. Ничего страшного — "
                    "можно попробовать ещё раз прямо в боте.</p>"
                )
        except Exception as e:  # noqa: BLE001 — страница не должна падать
            log.warning("Ошибка на странице оплаты: %s", e)
    return web.Response(text=_render(title, ico, body), content_type="text/html")


async def _mollie_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.post()
        payment_id = data.get("id")
        bot = request.app["bot"]
        if payment_id:
            await on_payment_paid(bot, payment_id)
    except Exception as e:  # noqa: BLE001 — Mollie всегда ждёт 200, иначе ретраит
        log.warning("Ошибка обработки webhook Mollie: %s", e)
    return web.Response(text="ok")


async def start_webserver(bot) -> web.AppRunner:
    """Запускает веб-сервер на нужном порту (для webhook оплаты и health-check)."""
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", _health)
    app.router.add_get("/thanks", _thanks)
    app.router.add_get("/privacy", _privacy)
    app.router.add_get("/terms", _terms)
    app.router.add_post("/mollie-webhook", _mollie_webhook)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    log.info("Веб-сервер запущен на порту %s", config.PORT)
    return runner
