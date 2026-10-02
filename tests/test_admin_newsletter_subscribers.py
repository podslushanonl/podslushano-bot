"""Focused checks for the newsletter subscriber view in Admin Center."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    runtime_path = ROOT / "handlers" / "admin_newsletter_subscribers.py"
    init_path = ROOT / "handlers" / "__init__.py"

    runtime = runtime_path.read_text(encoding="utf-8")
    handlers_init = init_path.read_text(encoding="utf-8")

    # Syntax must stay valid without importing the whole bot stack here.
    compile(runtime, str(runtime_path), "exec")

    assert "📨 Подписчики рассылки" in runtime
    assert "AdsNewsletterSubscriber" in runtime
    assert "row.email" in runtime
    assert "row.consent_at" in runtime
    assert "row.source" in runtime
    assert "row.is_active" in runtime
    assert "Страница /ads" in runtime
    assert "активна" in runtime
    assert "отписался" in runtime
    assert "_PAGE_SIZE = 12" in runtime
    assert ".offset(offset)" in runtime
    assert "ac:adsubs:" in runtime
    assert 'F.data.startswith("ac:adsubs")' in runtime
    assert "admin_newsletter_subscribers" in handlers_init

    print("[OK] Admin Center newsletter subscribers: email/date/source/status + pagination")


if __name__ == "__main__":
    main()
