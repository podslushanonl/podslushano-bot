"""Генерация счёта (factuur) в PDF и отправка на e-mail через Resend.

Цена считается ВКЛЮЧАЮЩЕЙ BTW (config.BTW_PERCENT). Номера счетов — сквозные
(хранятся в таблице Meta). Кириллица поддержана шрифтом DejaVu из папки fonts/.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
from datetime import date

import aiohttp

import config
from database.db import get_session
from database.models import Meta

log = logging.getLogger(__name__)

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_fonts_ready = False


def _ensure_fonts() -> None:
    """Регистрирует шрифт с кириллицей (один раз)."""
    global _FONT, _FONT_BOLD, _fonts_ready
    if _fonts_ready:
        return
    _fonts_ready = True
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")
        reg = os.path.join(base, "DejaVuSans.ttf")
        bold = os.path.join(base, "DejaVuSans-Bold.ttf")
        if os.path.exists(reg):
            pdfmetrics.registerFont(TTFont("DejaVu", reg))
            _FONT = "DejaVu"
        if os.path.exists(bold):
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold))
            _FONT_BOLD = "DejaVu-Bold"
    except Exception as e:  # noqa: BLE001
        log.warning("Шрифт для счёта не зарегистрирован: %s", e)


async def _next_invoice_no() -> str:
    async with get_session() as session:
        m = await session.get(Meta, "invoice_seq")
        n = (int(m.value) + 1) if m and m.value.isdigit() else 1
        await session.merge(Meta(key="invoice_seq", value=str(n)))
        await session.commit()
    return f"{date.today().year}-{n:04d}"


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0000FE0F\U00002190-\U000021FF]"
)


def _clean(text: str) -> str:
    """Убирает эмодзи/символы, которых нет в шрифте счёта."""
    return _EMOJI_RE.sub("", text or "").replace("  ", " ").strip()


def _eur(x: float) -> str:
    return f"€ {x:,.2f}".replace(",", " ")


def _build_pdf(no: str, buyer: str, email: str, description: str,
               excl: float, btw: float, total: float) -> bytes:
    _ensure_fonts()
    buyer, description = _clean(buyer), _clean(description)
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    x = 20 * mm
    y = h - 25 * mm

    c.setFont(_FONT_BOLD, 16)
    c.drawString(x, y, config.COMPANY_NAME)
    c.setFont(_FONT, 9)
    for line in [config.COMPANY_ADDRESS, f"KvK: {config.COMPANY_KVK}  ·  BTW: {config.COMPANY_BTW}",
                 config.COMPANY_EMAIL]:
        y -= 5 * mm
        c.drawString(x, y, line)

    # Заголовок счёта
    y -= 14 * mm
    c.setFont(_FONT_BOLD, 14)
    c.drawString(x, y, "FACTUUR / Счёт")
    c.setFont(_FONT, 10)
    y -= 7 * mm
    c.drawString(x, y, f"Factuurnummer / № счёта: {no}")
    y -= 5 * mm
    c.drawString(x, y, f"Datum / Дата: {date.today():%d-%m-%Y}")

    # Кому
    y -= 12 * mm
    c.setFont(_FONT_BOLD, 10)
    c.drawString(x, y, "Aan / Кому:")
    c.setFont(_FONT, 10)
    y -= 5 * mm
    c.drawString(x, y, buyer or "—")
    if email:
        y -= 5 * mm
        c.drawString(x, y, email)

    # Таблица
    y -= 14 * mm
    c.setFont(_FONT_BOLD, 10)
    c.drawString(x, y, "Omschrijving / Описание")
    c.drawRightString(w - 20 * mm, y, "Bedrag / Сумма")
    y -= 2 * mm
    c.line(x, y, w - 20 * mm, y)
    y -= 7 * mm
    c.setFont(_FONT, 10)
    c.drawString(x, y, description[:70])
    c.drawRightString(w - 20 * mm, y, _eur(total))

    # Итоги
    y -= 12 * mm
    for label, val, bold in [
        (f"Subtotaal (excl. BTW) / Без BTW", excl, False),
        (f"BTW {config.BTW_PERCENT:.0f}%", btw, False),
        ("Totaal / Итого", total, True),
    ]:
        c.setFont(_FONT_BOLD if bold else _FONT, 10)
        c.drawRightString(w - 60 * mm, y, label)
        c.drawRightString(w - 20 * mm, y, _eur(val))
        y -= 6 * mm

    # Подвал
    y -= 8 * mm
    c.setFont(_FONT, 9)
    c.drawString(x, y, "Bedrag voldaan via Mollie / Оплачено через Mollie.")
    y -= 5 * mm
    c.drawString(x, y, "Bedankt! / Спасибо за размещение в гайде Подслушано.nl 🙌")

    c.showPage()
    c.save()
    return buf.getvalue()


async def _send_email(to: str, subject: str, html: str, pdf: bytes, filename: str) -> bool:
    body = {
        "from": config.INVOICE_FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "html": html,
        "attachments": [{"filename": filename, "content": base64.b64encode(pdf).decode()}],
    }
    headers = {"Authorization": f"Bearer {config.RESEND_API_KEY}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.resend.com/emails", json=body, headers=headers) as r:
                if r.status >= 300:
                    log.warning("Resend error %s: %s", r.status, await r.text())
                    return False
                return True
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось отправить счёт: %s", e)
        return False


async def send_invoice(to_email: str, buyer_name: str, description: str, total_str: str) -> bool:
    """Создаёт счёт-PDF и отправляет на e-mail. True — если ушло."""
    if not config.invoice_enabled() or not to_email:
        return False
    try:
        total = float(total_str)
    except ValueError:
        return False
    excl = round(total / (1 + config.BTW_PERCENT / 100), 2)
    btw = round(total - excl, 2)
    no = await _next_invoice_no()
    pdf = _build_pdf(no, buyer_name, to_email, description, excl, btw, total)
    html = (
        f"<p>Здравствуйте!</p>"
        f"<p>Спасибо за размещение в гайде «Подслушано в Нидерландах». "
        f"Во вложении — счёт (factuur) №{no}.</p>"
        f"<p>С уважением,<br>{config.COMPANY_NAME}<br>{config.COMPANY_EMAIL}</p>"
    )
    return await _send_email(to_email, f"Счёт {no} · Podslushano.nl", html, pdf, f"factuur-{no}.pdf")
