"""Instagram Direct AI sales agent: Meta webhook -> durable inbox -> Mollie.

Feature gated. No outbound DMs/payments until explicitly enabled with Railway
settings and an approved Meta Instagram Messaging API integration.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import hmac
import html
import json
import logging
import os
import re
from uuid import uuid4

import aiohttp
from aiohttp import web
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError

import config
from database.db import get_session
from database.ig_sales_models import IgSalesConversation, IgSalesEvent, IgSalesOrder
from utils.payments import create_payment, get_payment
from utils.invoices import send_invoice

log = logging.getLogger(__name__)
router = Router()
PRODUCTS = ("ad_single", "ad_telegram", "ad_expert_live", "ad_promotion", "ad_campaign")
AD_RE = re.compile(r"реклам|продвижен|размещен|сотрудничест|коллаборац|advertis|promot|sponsor|рекламодат", re.I)
BUY_RE = re.compile(r"^(?:да|беру|подходит|согласн\w*|оформ\w*|оплат\w*|пришлите ссылку|хочу купить|давайте оформим)[\s!.?]*$", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
FINAL_STATUSES = {"paid", "canceled", "failed", "expired"}


def configured() -> bool:
    return bool(os.getenv("IG_SALES_ACCESS_TOKEN") and os.getenv("IG_SALES_ACCOUNT_ID")
                and os.getenv("IG_SALES_APP_SECRET") and os.getenv("IG_SALES_VERIFY_TOKEN"))


def enabled() -> bool:
    return os.getenv("IG_SALES_ENABLED", "0") == "1" and configured()


def send_enabled() -> bool:
    return enabled() and os.getenv("IG_SALES_SEND_ENABLED", "0") == "1"


def payment_enabled() -> bool:
    return send_enabled() and os.getenv("IG_SALES_PAYMENTS_ENABLED", "0") == "1" and config.payments_enabled()


def meta_signature_is_valid(payload: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature.startswith("sha256="):
        return False
    wanted = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:], wanted)


def catalog() -> dict:
    result = {}
    for key in PRODUCTS:
        product = config.AD_FORMATS.get(key)
        if product and not product.get("private"):
            option = config.ad_option(key, "std")
            if option:
                result[key] = {
                    "name": product["name"], "price": str(Decimal(str(option["price"])).quantize(Decimal("0.01"))),
                    "details": product.get("details", []),
                }
    return result


def choose_product(text: str) -> str:
    low = text.lower()
    if "telegram" in low or "телеграм" in low or "tg " in low:
        return "ad_telegram"
    if "под ключ" in low or "full service" in low or "кампани" in low:
        return "ad_campaign"
    if "эфир" in low or "q&a" in low or "вебинар" in low:
        return "ad_expert_live"
    if "несколько" in low or "два месяц" in low or "2 месяц" in low or "постоянн" in low:
        return "ad_promotion"
    return "ad_single"


async def ai_decision(text: str, current_product: str | None, previous: list) -> dict:
    """Model selects only a known product and intent; never sets amount or URL."""
    fallback = {
        "intent": "buy" if BUY_RE.fullmatch(text.strip()) else "quote",
        "product": choose_product(text) if not current_product else current_product,
        "risk": "none",
    }
    if not config.ANTHROPIC_API_KEY:
        return fallback
    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        catalog_data = catalog()
        response = await client.messages.create(
            model=config.AI_CHAT_MODEL,
            max_tokens=180,
            temperature=0,
            system=(
                "Ты классификатор входящего рекламного запроса Podslushano.nl. "
                "Верни только JSON: intent = quote | buy | question | handoff | stop; "
                "product = один из перечисленных ключей; risk = none | review. "
                "buy только при ЯВНОЙ просьбе оплатить уже предложенный тариф. "
                "Вопросы о юридических гарантиях, возвратах, индивидуальных условиях, "
                "конкурентах или сомнительном бизнесе требуют handoff/review. "
                "Никогда не придумывай тарифы, суммы или скидки. "
                "Разрешенные тарифы: " + ", ".join(catalog_data) + ". "
                "Текущий тариф: " + str(current_product or "нет") + "."
            ),
            messages=[{"role": "user", "content":
                       "Последние сообщения: " + json.dumps(previous[-4:], ensure_ascii=False)
                       + "\nНовое сообщение: " + text[:1200]}],
        )
        raw = "".join(p.text for p in response.content if getattr(p, "type", "") == "text")
        data = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        if data.get("intent") not in {"quote", "buy", "question", "handoff", "stop"}:
            return fallback
        if data.get("product") not in catalog_data:
            data["product"] = fallback["product"]
        if data.get("risk") not in {"none", "review"}:
            data["risk"] = "review"
        return data
    except Exception as exc:
        log.warning("IG sales classifier unavailable: %s", type(exc).__name__)
        return fallback


def quote_text(product_key: str) -> str:
    product = catalog()[product_key]
    details = product["details"][:4]
    desc = "\n".join("• " + item for item in details)
    terms = config.WEBHOOK_BASE_URL.rstrip("/") + "/terms" if config.WEBHOOK_BASE_URL else config.SITE_URL
    return (f"Здравствуйте! Я автоматический менеджер Podslushano.nl по рекламе. "
            f"Подойдёт формат «{product['name']}» — €{product['price']} с BTW.\n\n"
            f"{desc}\n\nПосле оплаты уточним дату и запросим материалы. "
            f"Дату согласуем с учётом доступных слотов. Условия: {terms}\n"
            f"Если всё подходит и вы согласны с условиями, напишите «Оформить» — "
            f"пришлю индивидуальную ссылку Mollie. Можно выбрать другой формат.")


async def answer_product_question(message: str, product_key: str) -> str:
    """Natural answers grounded in the immutable server-side catalogue."""
    product = catalog()[product_key]
    price = product["price"]
    text = message.lower()
    if re.search(r"фото|видео|материал|текст|описани|бриф", text):
        return "Фото, видео и описание можно прислать после оплаты, прямо в этот Direct. Мы поможем оформить материал под выбранный формат."
    if re.search(r"дат|когда|срок|публикац", text):
        return "Дату публикации согласуем после оплаты с учётом доступных слотов. Если нужен строго определённый день, напишите его — передадим на проверку."
    if re.search(r"сч[её]т|фактур|factuur|btw|квитанц", text):
        return "В цену включён BTW. Для factuur реквизиты запросим после оплаты и отправим PDF на указанный e-mail."
    if re.search(r"цен|стоим|сколько|скид|акци", text):
        return quote_text(product_key)
    if not config.ANTHROPIC_API_KEY:
        return ("Для формата «" + product["name"] + "» стоимость €" + price
                + " с BTW. Подскажите, что именно хотите уточнить?")
    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model=config.AI_CHAT_MODEL,
            max_tokens=180,
            temperature=0.2,
            system=(
                "Вы консультант Podslushano.nl в Instagram. Отвечайте естественно, "
                "уважительно, кратко и на «вы». Не выдумывайте факты или гарантии. "
                "Если ответ невозможен только из предоставленных сведений, "
                "напишите: «Это уточним у редакции». "
                "После оплаты материалы и дату согласовывают в переписке. "
                "Нельзя обещать конкретный день без подтверждения, продажи, "
                "подписчиков, гарантированные охваты или возвраты. "
                "Стоимость составляет строго €" + price + " (incl. BTW). "
                "Формат: " + product["name"] + ". Включено: "
                + "; ".join(product["details"][:8])
            ),
            messages=[{"role": "user", "content": message[:750]}],
        )
        result = "".join(block.text for block in response.content
                         if getattr(block, "type", None) == "text").strip()
        monetary = re.findall(r"(?:€|EUR\s*)\s*\d[\d.,]*", result, re.I)
        if monetary or not 5 <= len(result) <= 900:
            # Generated money amounts are disallowed, even correct ones: the
            # quote template alone owns numerical prices and conditions.
            return quote_text(product_key)
        return result
    except Exception:
        return "Уточним этот момент у редакции. Можете пока написать, какая задача у вашей рекламы?"



def invoice_request_text() -> str:
    return ("Оплата подтверждена! Спасибо. Материалы и дату согласуем здесь. "
            "Для оплаченной factuur, пожалуйста, отправьте одним сообщением три строки:\n"
            "1) Имя и фамилия / название компании\n"
            "2) Адрес с почтовым индексом и городом\n"
            "3) E-mail для счёта\n"
            "Пожалуйста, укажите реквизиты латиницей.")


def parse_invoice_lines(text: str) -> tuple[str, str, str] | None:
    lines = [x.strip() for x in text.strip().splitlines() if x.strip()]
    if len(lines) != 3:
        return None
    # Email must be a full third line; no scraping unrelated personal messages.
    name, address, email = lines
    if not EMAIL_RE.fullmatch(email) or not 2 <= len(name) <= 200 or not 8 <= len(address) <= 300:
        return None
    if re.search(r"[А-Яа-яЁё]", name + address):
        return None
    if not re.search(r"\d", address):
        return None
    return name, address, email.lower()


def response_window_open(last_inbound: datetime | None, now: datetime | None = None) -> bool:
    return bool(last_inbound and timedelta(0) <= (now or datetime.utcnow()) - last_inbound < timedelta(hours=24))


async def send_direct(ig_user_id: str, message: str, last_inbound: datetime | None) -> bool:
    if not send_enabled() or not response_window_open(last_inbound):
        return False
    version = os.getenv("IG_SALES_GRAPH_VERSION", "v23.0")
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise ValueError("Invalid Meta Graph API version")
    account = os.getenv("IG_SALES_ACCOUNT_ID", "")
    token = os.getenv("IG_SALES_ACCESS_TOKEN", "")
    url = f"https://graph.instagram.com/{version}/{account}/messages"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        async with session.post(url, headers={"Authorization": f"Bearer {token}"},
                json={"recipient": {"id": ig_user_id}, "message": {"text": message[:1900]}}) as response:
            if response.status >= 300:
                log.warning("Instagram send failed: HTTP %s", response.status)
                return False
            return True


async def alert_admin(bot, title: str, details: str) -> None:
    safe = html.escape(details[:1800])
    for admin in config.ADMIN_IDS:
        try:
            await bot.send_message(admin, f"<b>{html.escape(title)}</b>\n{safe}")
        except Exception:
            log.exception("IG sales could not notify admin")


async def verify_subscription(request: web.Request) -> web.Response:
    q = request.query
    valid = configured() and q.get("hub.mode") == "subscribe" and hmac.compare_digest(
        q.get("hub.verify_token", ""), os.getenv("IG_SALES_VERIFY_TOKEN", "")
    )
    if not valid:
        return web.Response(status=403, text="forbidden")
    return web.Response(text=q.get("hub.challenge", ""))


async def receive_webhook(request: web.Request) -> web.Response:
    body = await request.read()
    if len(body) > 256000:
        return web.Response(status=413)
    if not meta_signature_is_valid(
        body, request.headers.get("X-Hub-Signature-256", ""),
        os.getenv("IG_SALES_APP_SECRET", ""),
    ):
        return web.Response(status=403, text="invalid signature")
    if not enabled():
        return web.Response(text="disabled")
    try:
        payload = json.loads(body)
    except ValueError:
        return web.Response(status=400, text="invalid json")
    if payload.get("object") != "instagram":
        return web.Response(text="ignored")
    account = os.getenv("IG_SALES_ACCOUNT_ID", "")
    for entry in payload.get("entry", []):
        for item in entry.get("messaging", []):
            sender = str((item.get("sender") or {}).get("id") or "")
            receiver = str((item.get("recipient") or {}).get("id") or "")
            msg = item.get("message") or {}
            mid = str(msg.get("mid") or "")
            content = msg.get("text")
            if receiver != account or not sender or sender == account or not mid:
                continue
            if msg.get("is_echo") or not isinstance(content, str) or not content.strip():
                continue
            try:
                when = datetime.utcfromtimestamp(int(item.get("timestamp", 0)) / 1000)
            except (ValueError, TypeError, OverflowError):
                continue
            if not response_window_open(when) or len(content) > 6000:
                continue
            async with get_session() as session:
                if await session.get(IgSalesEvent, mid):
                    continue
                session.add(IgSalesEvent(
                    message_id=mid, ig_user_id=sender,
                    text=content[:3000], sent_at=when, status="pending",
                ))
                try:
                    await session.commit()
                except IntegrityError:
                    # Concurrent webhook retries can race on the same unique mid.
                    await session.rollback()
                    log.info("Deduplicated IG webhook message")
                except Exception:
                    await session.rollback()
                    raise  # Meta must retry instead of silently losing an event.
    return web.Response(text="ok")


async def create_checkout(conversation: IgSalesConversation) -> str:
    """Idempotent link for one conversation: never create a second open order."""
    if not payment_enabled():
        return "Оплата временно недоступна. Мы уже занимаемся подключением — напишите чуть позже."
    async with get_session() as session:
        existing = await session.scalar(
            select(IgSalesOrder).where(
                IgSalesOrder.ig_user_id == conversation.ig_user_id,
                IgSalesOrder.status.in_(("creating", "open")),
            ).order_by(IgSalesOrder.created_at.desc())
        )
        if existing and existing.checkout_url:
            return "Ссылка Mollie для оплаты вашего заказа: " + existing.checkout_url
        if existing:
            return "Оплата уже создаётся, попробуйте ещё раз через минуту."
        product = catalog().get(conversation.product_key or "")
        if not product:
            return "Уточните, пожалуйста, какой формат рекламы вам подходит."
        order_id = uuid4().hex
        session.add(IgSalesOrder(
            id=order_id, ig_user_id=conversation.ig_user_id,
            product_key=conversation.product_key, amount=product["price"],
            status="creating",
        ))
        current = await session.get(IgSalesConversation, conversation.ig_user_id)
        if current:
            current.order_id = order_id
        await session.commit()
    # NOTE: a checkout link (payments API) is single-use, and the existing
    # Mollie webhook dispatcher can verify it using metadata.
    payment = await create_payment(
        "Podslushano.nl — " + product["name"] + " #" + order_id[:8],
        {"kind": "ig_ad_sale", "order_id": order_id}, product["price"],
    )
    async with get_session() as session:
        order = await session.get(IgSalesOrder, order_id)
        if not payment or not payment.get("id") or not payment.get("checkout_url"):
            order.status = "error"
            await session.commit()
            return "Пока не удалось создать ссылку Mollie. Мы получили уведомление и проверим оплату."
        order.payment_id = payment["id"]
        order.checkout_url = payment["checkout_url"]
        order.status = "open"
        await session.commit()
    return ("Ссылка для оплаты через Mollie: " + payment["checkout_url"]
            + "\nСумма: €" + product["price"] + " с BTW. После оплаты вернёмся к материалам и дате.")


async def process_event(bot, event: IgSalesEvent) -> None:
    text = event.text.strip()
    async with get_session() as session:
        conv = await session.get(IgSalesConversation, event.ig_user_id)
        if conv is None:
            if not AD_RE.search(text):
                return  # Other editorial/support DMs must remain human-run.
            conv = IgSalesConversation(ig_user_id=event.ig_user_id)
            session.add(conv)
        if conv.state in {"handoff", "stopped"}:
            return
        if not conv.last_inbound_at or event.sent_at > conv.last_inbound_at:
            conv.last_inbound_at = event.sent_at
        try:
            history = json.loads(conv.history_json or "[]")
        except ValueError:
            history = []
        history.append({"role": "user", "text": text[:450]})
        state = conv.state
        product = conv.product_key
        await session.commit()

    reply = None
    action = None
    if state in {"paid", "awaiting_invoice"}:
        async with get_session() as session:
            current = await session.get(IgSalesConversation, event.ig_user_id)
            recent_order = await session.get(IgSalesOrder, current.order_id) if current.order_id else None
            invoice_done = bool(recent_order and recent_order.invoice_status in {"sent", "manual_review", "issuing"})
        if invoice_done and AD_RE.search(text):
            async with get_session() as session:
                current = await session.get(IgSalesConversation, event.ig_user_id)
                current.state, current.order_id = "new", None
                await session.commit()
            state, product = "new", None
        elif invoice_done:
            reply = "Спасибо! Заказ передан в работу. Материалы можно отправлять прямо сюда."
        else:
            parsed = parse_invoice_lines(text)
            if parsed:
                name, address, email = parsed
                async with get_session() as session:
                    current = await session.get(IgSalesConversation, event.ig_user_id)
                    current.invoice_name, current.invoice_address, current.invoice_email = name, address, email
                    current.state = "awaiting_invoice"
                    await session.commit()
                action = "invoice"
                reply = "Спасибо! Реквизиты для factuur получены. Проверяем отправку счёта."
            else:
                reply = invoice_request_text()
    if state not in {"paid", "awaiting_invoice"}:
        decision = await ai_decision(text, product, history)
        intent = decision.get("intent")
        if intent == "stop":
            async with get_session() as session:
                conv = await session.get(IgSalesConversation, event.ig_user_id)
                conv.state = "stopped"
                await session.commit()
            reply = "Хорошо, больше не будем присылать вам автоматические сообщения."
        elif intent == "handoff" or decision.get("risk") == "review":
            async with get_session() as session:
                conv = await session.get(IgSalesConversation, event.ig_user_id)
                conv.state = "handoff"
                await session.commit()
            await alert_admin(bot, "IG Direct: требуется сотрудник", "IG user: " + event.ig_user_id + "\n" + text[:750])
            reply = "Спасибо! Передали ваш вопрос редакции, ответим лично."
        elif intent == "buy" and product and state == "quoted":
            action = "checkout"
        elif intent == "question" and product:
            reply = await answer_product_question(text, product)
        else:
            selected = decision.get("product") or product or choose_product(text)
            if selected not in catalog():
                selected = "ad_single"
            async with get_session() as session:
                conv = await session.get(IgSalesConversation, event.ig_user_id)
                conv.product_key = selected
                conv.state = "quoted"
                await session.commit()
            reply = quote_text(selected)
    if action == "checkout":
        async with get_session() as session:
            conv = await session.get(IgSalesConversation, event.ig_user_id)
            reply = await create_checkout(conv)
    if action == "invoice":
        await issue_invoice(bot, event.ig_user_id)
    if reply:
        async with get_session() as session:
            conv = await session.get(IgSalesConversation, event.ig_user_id)
            inbound = conv.last_inbound_at
        if send_enabled() and response_window_open(inbound):
            if not await send_direct(event.ig_user_id, reply, inbound):
                raise RuntimeError("Instagram message delivery failed")
        history.append({"role": "assistant", "text": reply[:450]})
        async with get_session() as session:
            conv = await session.get(IgSalesConversation, event.ig_user_id)
            conv.history_json = json.dumps(history[-10:], ensure_ascii=False)
            await session.commit()


async def issue_invoice(bot, ig_user_id: str) -> None:
    async with get_session() as session:
        conv = await session.get(IgSalesConversation, ig_user_id)
        if not conv or not all((conv.invoice_name, conv.invoice_address, conv.invoice_email)):
            return
        order = await session.scalar(select(IgSalesOrder).where(
            IgSalesOrder.ig_user_id == ig_user_id, IgSalesOrder.status == "paid",
        ).order_by(IgSalesOrder.created_at.desc()))
        if not order or order.invoice_status != "not_requested":
            return
        # Mark before side effect: retry cannot create a second legally-numbered invoice.
        order.invoice_status = "issuing"
        await session.commit()
        order_id, name, address, email, amount = (
            order.id, conv.invoice_name, conv.invoice_address, conv.invoice_email, order.amount
        )
    try:
        ok, detail = await send_invoice(
            email, name, "Рекламное размещение Podslushano.nl #" + order_id[:8],
            amount, buyer_lines=[name, address, email],
        )
    except Exception as exc:
        ok, detail = False, type(exc).__name__
    async with get_session() as session:
        order = await session.get(IgSalesOrder, order_id)
        order.invoice_status = "sent" if ok else "manual_review"
        await session.commit()
    if not ok:
        await alert_admin(bot, "IG Direct: фактура требует проверки",
                          "Заказ: " + order_id + "\nОшибка: " + detail[:250])


async def on_payment(bot, payment_id: str, payment: dict) -> None:
    metadata = payment.get("metadata") or {}
    if metadata.get("kind") != "ig_ad_sale":
        return
    oid = str(metadata.get("order_id") or "")
    if not oid:
        return
    status = str(payment.get("status") or "")
    async with get_session() as session:
        order = await session.get(IgSalesOrder, oid)
        if not order or order.payment_id != payment_id:
            return
        expected = Decimal(order.amount)
        paid_value = (payment.get("amount") or {}).get("value")
        if (payment.get("amount") or {}).get("currency") != "EUR" or paid_value is None:
            return
        if Decimal(str(paid_value)) != expected:
            log.error("IG sales Mollie amount mismatch on order %s", oid)
            await alert_admin(bot, "IG sales: ошибка суммы оплаты", "Order " + oid)
            return
        if status == "paid":
            if order.status == "paid":
                return
            order.status = "paid"
            order.paid_at = datetime.utcnow()
            conv = await session.get(IgSalesConversation, order.ig_user_id)
            if conv:
                conv.state = "paid"
            await session.commit()
            inbound = conv.last_inbound_at if conv else None
            user = order.ig_user_id
        elif status in {"failed", "canceled", "expired"}:
            if order.status != "paid":
                order.status = status
                await session.commit()
            return
        else:
            return
    await alert_admin(bot, "IG Direct: оплата рекламы", "Заказ " + oid + " · €" + str(expected))
    if response_window_open(inbound):
        try:
            await send_direct(user, invoice_request_text(), inbound)
        except Exception:
            log.exception("IG sales paid DM confirmation not sent")


async def worker_loop(bot) -> None:
    if not enabled():
        log.info("Instagram sales agent OFF: set IG_SALES_ENABLED after Meta setup")
        return
    # Recover events interrupted by a worker restart.
    async with get_session() as session:
        await session.execute(update(IgSalesEvent).where(
            IgSalesEvent.status == "processing").values(status="pending"))
        await session.commit()
    while True:
        try:
            async with get_session() as session:
                event = await session.scalar(select(IgSalesEvent).where(
                    IgSalesEvent.status == "pending"
                ).order_by(IgSalesEvent.sent_at, IgSalesEvent.created_at))
                if event:
                    event.status = "processing"
                    event.attempts += 1
                    await session.commit()
                    mid = event.message_id
                else:
                    mid = None
            if not mid:
                await asyncio.sleep(3)
                continue
            try:
                await process_event(bot, event)
            except Exception as exc:
                log.exception("IG sales process failed for %s", mid)
                async with get_session() as session:
                    found = await session.get(IgSalesEvent, mid)
                    found.status = "failed" if found.attempts >= 3 else "pending"
                    await session.commit()
                if event.attempts >= 3:
                    await alert_admin(bot, "IG Direct: ошибка обработки", "Событие " + mid + ": " + type(exc).__name__)
                await asyncio.sleep(5)
            else:
                async with get_session() as session:
                    found = await session.get(IgSalesEvent, mid)
                    found.status = "done"
                    await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("IG sales worker error")
            await asyncio.sleep(10)


async def payment_reconciliation_loop(bot) -> None:
    """Recover payments whose Mollie webhook arrived early or was dropped."""
    if not enabled():
        return
    while True:
        try:
            async with get_session() as session:
                ids = (await session.scalars(select(IgSalesOrder.payment_id).where(
                    IgSalesOrder.status == "open",
                    IgSalesOrder.payment_id.is_not(None),
                ).limit(50))).all()
            for payment_id in ids:
                payment = await get_payment(payment_id)
                if payment:
                    await on_payment(bot, payment_id, payment)
            # Limit the lifetime of raw DM messages and model dialogue history.
            cutoff = datetime.utcnow() - timedelta(days=30)
            async with get_session() as session:
                await session.execute(delete(IgSalesEvent).where(
                    IgSalesEvent.created_at < cutoff,
                    IgSalesEvent.status.in_(("done", "failed")),
                ))
                await session.execute(update(IgSalesConversation).where(
                    IgSalesConversation.updated_at < cutoff,
                ).values(history_json="[]"))
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Instagram sales Mollie reconciliation failed")
        await asyncio.sleep(120)


async def payment_return(request: web.Request) -> web.Response:
    # Public page never trusts a redirect as evidence that a payment succeeded.
    content = ("<h1>Спасибо!</h1><p>Статус платежа проверяется через Mollie. "
               "После подтверждения напишем вам в Instagram Direct, если чат активен."
               "</p><p>Материалы можно прислать позже.</p>")
    return web.Response(text=(
        "<!doctype html><html lang='ru'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Podslushano.nl · Оплата</title><body style='font:18px system-ui;"
        "max-width:520px;margin:12vh auto;padding:24px'>" + content + "</body></html>"
    ), content_type="text/html", headers={"Cache-Control": "no-store"})


def install_routes(app: web.Application) -> None:
    app.router.add_get("/webhooks/instagram-sales", verify_subscription)
    app.router.add_post("/webhooks/instagram-sales", receive_webhook)
    app.router.add_get("/instagram-sales/payment-return", payment_return)


@router.message(Command("igsales"))
async def admin_sales_command(message: Message) -> None:
    if not message.from_user or message.from_user.id not in config.ADMIN_IDS:
        return
    parts = (message.text or "").split()
    if len(parts) == 3 and parts[1] in {"pause", "resume"}:
        async with get_session() as session:
            conv = await session.get(IgSalesConversation, parts[2])
            if not conv:
                await message.answer("Диалог не найден.")
                return
            conv.state = "handoff" if parts[1] == "pause" else "new"
            await session.commit()
        await message.answer("Управление диалогом обновлено.")
        return
    async with get_session() as session:
        recent = (await session.scalars(select(IgSalesOrder).order_by(
            IgSalesOrder.created_at.desc()).limit(5))).all()
    rows = [f"{o.id[:8]} | €{o.amount} | {o.status}" for o in recent]
    await message.answer(
        "Instagram Sales Agent\n"
        f"configured: {configured()}\nprocessing: {enabled()}\n"
        f"outbound: {send_enabled()}\npayments: {payment_enabled()}\n"
        "Последние заказы:\n" + ("\n".join(rows) or "—")
        + "\n/igsales pause IG_USER_ID — передать человеку"
        + "\n/igsales resume IG_USER_ID — продолжить AI"
    )
