"""Админский доступ к постоянному архиву factuur.

Команда /invoices YYYY-MM собирает сохранённые PDF за месяц в ZIP и отправляет
его администратору в Telegram. Для августа 2026 умеет восстановить четыре
исторические продажи с ТОЧНЫМИ уже выданными номерами 2026-0025..0028.

Восстановление сначала пытается забрать ОРИГИНАЛЬНЫЙ PDF из Resend, пока он ещё
доступен в журнале. Если Resend уже удалил письмо, используется неизменяемый
исторический snapshot. Live AdBooking/Specialist намеренно не используются:
текущая база и текущие тарифы не являются источником истины для старой фактуры.
Ничего повторно клиентам не отправляется и invoice_seq не меняется.
"""
from __future__ import annotations

import os
import re
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

import config
from utils.invoices import (
    archive_invoice_copy,
    invoice_archive_path,
    invoice_archive_root,
)

router = Router()
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_RESEND_API = "https://api.resend.com"
_AMSTERDAM = ZoneInfo("Europe/Amsterdam")


# Неизменяемые данные уже состоявшихся продаж. Они нужны только как fallback,
# если оригинальный PDF больше нельзя получить из Resend. Никаких запросов к
# текущей AdBooking/Specialist здесь быть не должно: карточки и тарифы меняются.
_AUGUST_2026 = [
    {
        "no": "2026-0025",
        "invoice_date": date(2026, 8, 7),
        "buyer_name": "Good House NL",
        "buyer_lines": [
            "Good House NL",
            "Vitalii Vasyna",
            "good.house.nl.info@gmail.com",
        ],
        "description": "Реклама «Продвижение» (4 выхода / 2 месяца)",
        "amount": "180.00",
    },
    {
        "no": "2026-0026",
        "invoice_date": date(2026, 8, 23),
        "buyer_name": "Margaryta_Laser Hair Removal in Utrecht",
        "buyer_lines": [
            "Margaryta_Laser Hair Removal in Utrecht",
            "margarita.ryabok@gmail.com",
        ],
        "description": (
            "Vermelding in Podslushano-gids: "
            "Margaryta_Laser Hair Removal in Utrecht (месяц)"
        ),
        "amount": "9.99",
    },
    {
        "no": "2026-0027",
        "invoice_date": date(2026, 8, 24),
        "buyer_name": "Inburgering.org",
        "buyer_lines": ["Inburgering.org", "info@inburgering.org"],
        "description": "Vermelding in Podslushano-gids: Inburgering.org (год)",
        "amount": "99.00",
    },
    {
        "no": "2026-0028",
        "invoice_date": date(2026, 8, 27),
        "buyer_name": "MRE FINANCE",
        "buyer_lines": [
            "MRE FINANCE",
            "Emre Donmez",
            "BTW: NL003735526B54",
            "KVK: 82821348",
            "info@mrefinance.nl",
            "+31 6 41095486",
        ],
        "description": (
            "Реклама «NUMR — campagne van 2 maanden» "
            "(Volledige campagne / 2 maanden)"
        ),
        "amount": "299.00",
    },
]


def _archive_raw_pdf(no: str, invoice_date: date, pdf: bytes) -> Path:
    """Атомарно кладёт уже существующий оригинальный PDF на Railway volume."""
    if not pdf.startswith(b"%PDF"):
        raise RuntimeError("Resend вернул не PDF")
    path = invoice_archive_path(no, invoice_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(pdf)
    os.replace(tmp, path)
    return path


async def _restore_original_from_resend(no: str, invoice_date: date) -> tuple[bool, str]:
    """Ищет письмо по точному subject и сохраняет его оригинальный PDF.

    Resend хранит журнал ограниченное время, поэтому отсутствие письма здесь не
    считается фатальной ошибкой — вызывающий код использует historical snapshot.
    """
    if not config.RESEND_API_KEY:
        return False, "RESEND_API_KEY не настроен"

    headers = {"Authorization": f"Bearer {config.RESEND_API_KEY}"}
    subject = f"Счёт {no} · Podslushano.nl"
    email_row: dict | None = None
    after: str | None = None

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # 5 × 100 более чем достаточно для текущего журнала, но при этом не
            # превращаем восстановление в бесконечный обход Resend.
            for _ in range(5):
                params: dict[str, str] = {"limit": "100"}
                if after:
                    params["after"] = after
                async with session.get(
                    f"{_RESEND_API}/emails", headers=headers, params=params
                ) as response:
                    if response.status >= 300:
                        return False, f"Resend list HTTP {response.status}"
                    payload = await response.json()
                rows = payload.get("data") or []
                email_row = next(
                    (row for row in rows if row.get("subject") == subject), None
                )
                if email_row:
                    break
                if not payload.get("has_more") or not rows:
                    break
                after = rows[-1].get("id")
                if not after:
                    break

            if not email_row or not email_row.get("id"):
                return False, f"оригинал {no} уже не найден в журнале Resend"

            email_id = email_row["id"]
            async with session.get(
                f"{_RESEND_API}/emails/{email_id}/attachments", headers=headers
            ) as response:
                if response.status >= 300:
                    return False, f"Resend attachments HTTP {response.status}"
                payload = await response.json()
            attachments = payload.get("data") or []
            filename = f"factuur-{no}.pdf"
            attachment = next(
                (item for item in attachments if item.get("filename") == filename),
                None,
            )
            if attachment is None:
                attachment = next(
                    (
                        item
                        for item in attachments
                        if str(item.get("filename", "")).lower().endswith(".pdf")
                    ),
                    None,
                )
            if attachment is None:
                return False, f"у письма {no} нет PDF-вложения"

            download_url = attachment.get("download_url")
            if not download_url and attachment.get("id"):
                async with session.get(
                    f"{_RESEND_API}/emails/{email_id}/attachments/{attachment['id']}",
                    headers=headers,
                ) as response:
                    if response.status >= 300:
                        return False, f"Resend attachment HTTP {response.status}"
                    detail = await response.json()
                download_url = detail.get("download_url")
            if not download_url:
                return False, f"Resend не выдал download_url для {no}"

            async with session.get(download_url) as response:
                if response.status >= 300:
                    return False, f"Resend CDN HTTP {response.status}"
                pdf = await response.read()

        _archive_raw_pdf(no, invoice_date, pdf)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _restore_snapshot(item: dict) -> Path:
    """Создаёт бухгалтерскую копию из зафиксированных исторических данных."""
    return archive_invoice_copy(
        item["no"],
        item["invoice_date"],
        item["buyer_name"],
        item["description"],
        item["amount"],
        buyer_lines=item["buyer_lines"],
    )


async def ensure_august_2026_archive() -> list[str]:
    """Гарантирует наличие четырёх августовских factuur на volume."""
    errors: list[str] = []
    for item in _AUGUST_2026:
        no = item["no"]
        invoice_date = item["invoice_date"]
        path = invoice_archive_path(no, invoice_date)
        if path.exists() and path.stat().st_size > 0:
            continue

        restored, resend_reason = await _restore_original_from_resend(
            no, invoice_date
        )
        if restored:
            continue

        try:
            _restore_snapshot(item)
        except Exception as exc:  # noqa: BLE001 — продолжаем остальные фактуры
            errors.append(
                f"{no}: Resend: {resend_reason}; snapshot: "
                f"{type(exc).__name__}: {exc}"
            )
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
        today = datetime.now(_AMSTERDAM).date()
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
