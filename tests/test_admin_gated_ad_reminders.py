"""Checks for admin-gated advertiser material reminders."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ad_material_reminder_runtime as smart  # noqa: E402
import ad_material_admin_gate_runtime as gate  # noqa: E402
from utils import ad_reminders, ad_sales_pipeline  # noqa: E402


def booking() -> SimpleNamespace:
    return SimpleNamespace(
        id=321,
        company="Kova Executive",
        buyer_name=None,
        fmt="ad_single",
        email="client@example.com",
        materials_status="waiting",
        status="paid",
        dates_csv="2026-09-23",
    )


def main() -> None:
    # Scheduler stages: admin gets an early check, then one explicit decision per email.
    assert gate._stage_for_days(3) == "72h_check"
    assert gate._stage_for_days(2) == "48h"
    assert gate._stage_for_days(1) == "24h"
    assert gate._stage_for_days(0) == "day_of"
    assert gate._stage_for_days(4) is None
    assert gate._stage_for_days(-1) is None

    # Effective production scheduler is the admin-gated one: no blind client sequence.
    assert ad_reminders.process_ad_reminders is gate.process_ad_reminders

    # A generic Telegram conversation no longer auto-marks materials as discussion.
    assert ad_sales_pipeline.record_message is smart._original_record_message

    # Gmail is a hint, never the source of truth.
    assert "возможно" in gate._gmail_hint(smart.MailboxResult(True, "received", "x")).lower()
    assert "не обнаружены" in gate._gmail_hint(smart.MailboxResult(True, "discussion", "x")).lower()
    assert "не влияет на решение" in gate._gmail_hint(smart.MailboxResult(False, None, "x")).lower()

    # Client copy is human, channel-neutral and does not promise an automatic reschedule.
    subject48, _, text48 = gate._message(booking(), "2026-09-23", "48h")
    assert "Материалы для рекламы" in subject48
    assert "48 часов" in text48
    assert "Telegram, Instagram или WhatsApp" in text48
    assert "можно просто проигнорировать" in text48

    subject24, _, text24 = gate._message(booking(), "2026-09-23", "24h")
    assert "завтрашней рекламы" in subject24
    assert "24 часа" in text24
    assert "сегодня" in text24.lower()

    subject0, _, text0 = gate._message(booking(), "2026-09-23", "day_of")
    assert "нужны дальнейшие действия" in subject0.lower()
    assert "сегодня выйти не может" in text0
    assert "если перенос на другую дату возможен" in text0.lower()
    assert "не назначается автоматически" in text0.lower()
    assert "перенос подтверждён" not in text0.lower()

    # Buttons never send anything at the 72h pre-check; email-send appears only later.
    kb72 = gate._keyboard(321, "2026-09-23", "72h_check")
    callbacks72 = [b.callback_data for row in kb72.inline_keyboard for b in row]
    assert any(c.startswith("adgate:wait:") for c in callbacks72)
    assert not any(c.startswith("adgate:send:") for c in callbacks72)

    kb48 = gate._keyboard(321, "2026-09-23", "48h")
    callbacks48 = [b.callback_data for row in kb48.inline_keyboard for b in row]
    assert any(c.startswith("adgate:send:") for c in callbacks48)

    print("[OK] admin-gated ad reminders: explicit admin decision + safe copy")


if __name__ == "__main__":
    main()
