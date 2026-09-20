"""Проверка сценария: 72h → админ «нет» → preview без отправки."""
import inspect
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ad_material_admin_gate_runtime as gate  # noqa: E402
import ad_material_72h_preview_runtime as preview  # noqa: E402


def booking() -> SimpleNamespace:
    return SimpleNamespace(
        id=777,
        company="Test Advertiser",
        buyer_name=None,
        fmt="ad_single",
        email="client@example.com",
        materials_status="waiting",
        status="paid",
        dates_csv="2026-09-23",
    )


def main() -> None:
    # За 3 дня остаётся только безопасная кнопка «материалов нет», без send callback.
    kb = gate._keyboard(777, "2026-09-23", "72h_check")
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "adgate:wait:777:2026-09-23" in callbacks
    assert not any(c.startswith("adgate:send:") for c in callbacks)

    # После ответа «нет» готовится именно первое 48h-письмо и явно помечается как НЕ отправленное.
    text = preview.build_48h_preview(booking(), "2026-09-23")
    assert "Первое письмо подготовлено" in text
    assert "48 часов" in text
    assert "Клиенту ничего не отправлено" in text
    assert "Нет — отправить письмо за 48 часов" in text

    # Сам 72h callback не имеет права вызывать отправку email.
    source = inspect.getsource(preview.confirm_72h_no_materials)
    assert "_send_one" not in source
    assert "send_email_message" not in source

    # В реальном bot.py preview-router должен стоять раньше общего gate-router,
    # иначе старый adgate:wait обработчик перехватит callback первым.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "bot.py"), "r", encoding="utf-8") as fh:
        bot_source = fh.read()
    assert bot_source.index("dp.include_router(ad_material_72h_preview_runtime.router)") < bot_source.index(
        "dp.include_router(ad_material_admin_gate_runtime.router)"
    )

    print("[OK] 72h: admin no → 48h draft preview → no automatic send")


if __name__ == "__main__":
    main()
