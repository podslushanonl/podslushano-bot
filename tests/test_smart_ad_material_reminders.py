"""Focused checks for smart advertiser material reminders."""
from email.message import EmailMessage
from types import SimpleNamespace

import ad_material_reminder_runtime as smart
from utils import ad_sales_pipeline


def booking() -> SimpleNamespace:
    return SimpleNamespace(
        id=321,
        company="Kova Executive",
        buyer_name=None,
        fmt="ad_single",
        email="client@example.com",
    )


def main() -> None:
    # Paid clients stay in the tracked ad conversation after payment.
    assert "paid" in ad_sales_pipeline.ACTIVE_SALES

    # Production stages are explicit; every non-waiting material stage is silent.
    assert "materials_discussion" in ad_sales_pipeline.PRODUCTION_LABELS
    assert "materials_partial" in ad_sales_pipeline.PRODUCTION_LABELS
    assert "preparing" in ad_sales_pipeline.PRODUCTION_LABELS
    for state in ("discussion", "partial", "received", "preparing", "scheduled", "published", "completed"):
        assert state in smart.SILENT_MATERIAL_STATES

    # Reminder copy is concise and does not invent an automatic cancellation/hold.
    subject48, html48, text48 = smart._message(booking(), "2026-09-21", "48h")
    assert "Материалы для рекламы" in subject48
    assert "если материалы уже у нас" in text48.lower()
    assert len(text48) < 1400

    subject24, _, text24 = smart._message(booking(), "2026-09-21", "24h")
    assert "Напоминание" in subject24
    assert "нет отметки" in text24
    assert len(text24) < 1500

    subject0, html0, text0 = smart._message(booking(), "2026-09-21", "day_of")
    assert "сегодняшней рекламы" in subject0.lower()
    assert "не отменяет и не переносит" in text0
    assert "приостановлено" not in (html0 + text0).lower()

    # A normal reply means discussion; a file/cloud link means materials arrived.
    plain = EmailMessage()
    plain.set_content("Добрый день, сейчас уточню цену и пришлю финальную версию.")
    assert not smart._message_has_materials(plain)

    linked = EmailMessage()
    linked.set_content("Материалы здесь: https://drive.google.com/drive/folders/abc")
    assert smart._message_has_materials(linked)

    attached = EmailMessage()
    attached.set_content("Отправляю материалы")
    attached.add_attachment(b"fake-image", maintype="image", subtype="jpeg", filename="creative.jpg")
    assert smart._message_has_materials(attached)

    # Without mailbox credentials the code must report no visibility, not pretend
    # that it checked inbox. The scheduler then allows at most one blind email.
    imap = smart._imap_mailbox_check("client@example.com", __import__("datetime").datetime.utcnow())
    assert imap.available is False

    print("[OK] smart ad material reminders: state guard + mailbox detection + copy")


if __name__ == "__main__":
    main()
