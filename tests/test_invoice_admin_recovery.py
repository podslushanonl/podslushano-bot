"""Focused regression checks for historical invoice recovery."""
from datetime import date


def test_august_invoice_snapshots_are_immutable_and_complete():
    from handlers import invoice_admin

    items = {item["no"]: item for item in invoice_admin._AUGUST_2026}
    assert set(items) == {
        "2026-0025", "2026-0026", "2026-0027", "2026-0028"
    }
    assert items["2026-0025"]["invoice_date"] == date(2026, 8, 7)
    assert items["2026-0025"]["amount"] == "180.00"
    assert "Good House NL" in items["2026-0025"]["buyer_lines"]
    assert items["2026-0028"]["invoice_date"] == date(2026, 8, 27)
    assert items["2026-0028"]["amount"] == "299.00"
    assert "MRE FINANCE" in items["2026-0028"]["buyer_lines"]


def test_historical_recovery_does_not_import_mutable_booking_models():
    from pathlib import Path

    source = Path("handlers/invoice_admin.py").read_text(encoding="utf-8")
    assert "database.models" not in source
    assert "select(AdBooking)" not in source
    assert "select(Specialist)" not in source
    assert "_restore_original_from_resend" in source
