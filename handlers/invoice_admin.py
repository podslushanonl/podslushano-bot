"""Админский доступ к постоянному архиву factuur.

Команда /invoices YYYY-MM собирает сохранённые PDF за месяц в ZIP и отправляет
его администратору в Telegram. Для августа 2026 умеет один раз восстановить
четыре исторические продажи с ТОЧНЫМИ уже выданными номерами 2026-0025..0028.
Восстановление ничего не отправляет клиентам и не меняет invoice_seq.
"""
from __future__ import annotations

import os
import re
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message
from sqlalchemy import select

import config
from database.db import get_session
from database.models import AdBooking, Specialist
from utils.invoices import (
    archive_invoice_copy,
    invoice_archive_path,
    invoice_archive_root,
)

router = Router()
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


async def _specialist_invoice(
    *, no: str, invoice_date: date, email: str, amount: str
) -> Path:
    async with get_session() as session:
        row = await session.scalar(
            select(Specialist)
            .where(Specialist.invoice_email == email)
            .order_by(Specialist.id.desc())
        )
    if row is None:
        raise RuntimeError(f"не найдена карточка специалиста для {email}")
    plan = config.plan_info(row.plan)
    description = f"Vermelding in Podslushano-gids: {row.name} ({plan['title']})"
    return archive_invoice_copy(
        no,
        invoice_date,
        row.name,
        description,
        amount,
        buyer_lines=[row.name, email],
    )


async def _ad_invoice(
    *, no: str, invoice_date: date, email: str, amount: str
) -> Path:
    async with get_session() as session:
        row = await session.scalar(
            select(AdBooking)
            .where(
                AdBooking.status == "paid",
                AdBooking.email == email,
                AdBooking.amount == amount,
            )
            .order_by(AdBooking.id.desc())
        )
    if row is None:
        raise RuntimeError(f"не найдена оплаченная рекламная бронь для {email}")

    info = config.AD_FORMATS.get(row.fmt, {"name": row.fmt})
    option = config.ad_option(row.fmt, row.opt) or {"label": row.opt}
    addon = config.ad_addon(row.fmt) if row.addon else None
    addon_sfx = f" + {addon['label']}" if addon else ""
    description = (
        f"Реклама «{info['name']}» ({option.get('label', '')}{addon_sfx}) — "
        f"{row.dates_csv or row.date}"
    )

    if row.client_type == "business":
        buyer_name = row.company or "—"
        buyer_lines = [
            row.company,
            row.address,
            row.postcode,
            f"BTW: {row.btw}" if row.btw else None,
            f"KVK: {row.kvk}" if row.kvk else None,
            row.email,
            row.phone,
        ]
    else:
        buyer_name = row.buyer_name or row.company or "—"
        buyer_lines = [row.buyer_name or row.company, row.address, row.email]
    buyer_lines = [value for value in buyer_lines if value]

    return archive_invoice_copy(
        no,
        invoice_date,
        buyer_name,
        description,
        amount,
        buyer_lines=buyer_lines,
    )


async def ensure_august_2026_archive() -> list[str]:
    """Восстанавливает четыре августовских factuur, если их ещё нет на volume."""
    errors: list[str] = []
    # Номера 0026, 0027 и 0028 подтверждены историей Resend. Продажа Good House
    # от 07-08-2026 — предыдущая из четырёх августовских продаж, поэтому её
    # уже выданный номер в сквозной последовательности — 2026-0025.
    items = [
        ("ad", "2026-0025", date(2026, 8, 7), "good.house.nl.info@gmail.com", "180.00"),
        ("specialist", "2026-0026", date(2026, 8, 23), "margarita.ryabok@gmail.com", "9.99"),
        ("specialist", "2026-0027", date(2026, 8, 24), "info@inburgering.org", "99.00"),
        ("ad", "2026-0028", date(2026, 8, 27), "info@mrefinance.nl", "299.00"),
    ]
    for kind, no, invoice_date, email, amount in items:
        path = invoice_archive_path(no, invoice_date)
        if path.exists() and path.stat().st_size > 0:
            continue
        try:
            if kind == "ad":
                await _ad_invoice(
                    no=no,
                    invoice_date=invoice_date,
                    email=email,
                    amount=amount,
                )
            else:
                await _specialist_invoice(
                    no=no,
                    invoice_date=invoice_date,
                    email=email,
                    amount=amount,
                )
        except Exception as exc:  # noqa: BLE001 — продолжаем остальные фактуры
            errors.append(f"{no}: {type(exc).__name__}: {exc}")
    return errors


def _month_folder(month_key: str) -> Path:
    year, month = month_key.split("-", 1)
    return invoice_archive_root() / year / month


@router.message(Command("invoices"))
async def invoices_archive(message: Message) -> None:
    if message.from_user is None or message.from_user.id not in config.ADMIN_IDS:
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2:
        month_key = parts[1].strip()
    else:
        today = date.today()
        month_key = f"{today.year:04d}-{today.month:02d}"
    if not _MONTH_RE.fullmatch(month_key):
        await message.answer("Формат: /invoices YYYY-MM, например /invoices 2026-08")
        return
    year, month = map(int, month_key.split("-"))
    if not 1 <= month <= 12:
        await message.answer("Месяц должен быть от 01 до 12.")
        return

    errors: list[str] = []
    if month_key == "2026-08":
        errors = await ensure_august_2026_archive()

    folder = _month_folder(month_key)
    pdfs = sorted(folder.glob("factuur-*.pdf")) if folder.exists() else []
    if not pdfs:
        detail = "\n".join(errors[:4])
        await message.answer(
            f"В архиве нет фактур за {month_key}." + (f"\n{detail}" if detail else "")
        )
        return

    fd, zip_name = tempfile.mkstemp(prefix=f"facturen-{month_key}-", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(zip_name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for pdf in pdfs:
                archive.write(pdf, arcname=pdf.name)
        caption = f"Facturen {month_key} · {len(pdfs)} шт."
        if errors:
            caption += f"\nНе восстановлено: {len(errors)}. Детали отправлю ниже."
        await message.answer_document(
            document=FSInputFile(zip_name, filename=f"facturen-{month_key}.zip"),
            caption=caption,
        )
        if errors:
            await message.answer("Ошибки восстановления:\n" + "\n".join(errors))
    finally:
        try:
            os.unlink(zip_name)
        except FileNotFoundError:
            pass
