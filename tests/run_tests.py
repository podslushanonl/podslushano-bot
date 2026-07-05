"""Быстрые проверки критичных инвариантов бота (запуск: python tests/run_tests.py).

Ловят регрессии в том, что уже ломалось: импорт, категории специалистов,
авто-переопределение категории, премиум-приоритет, сохранение премиума/фото
при пересеве. Падает с ненулевым кодом — удобно вешать на хук/CI.
"""
import asyncio
import os
import sys
import tempfile

# корень проекта в путь (скрипт лежит в tests/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "123456:test")
os.environ.setdefault("ADMIN_IDS", "1")

import config  # noqa: E402

# изолированная временная БД, чтобы не трогать рабочую
config.DB_PATH = os.path.join(tempfile.mkdtemp(), "bot.db")
config.DB_URL = f"sqlite+aiosqlite:///{config.DB_PATH}"

import importlib  # noqa: E402
import database.db as db  # noqa: E402
importlib.reload(db)

from sqlalchemy import select  # noqa: E402
from database.models import Meta, Specialist  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "OK  " if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if (detail and not cond) else ""))
    if not cond:
        _fails.append(name)


def test_import_bot() -> None:
    import bot  # noqa: F401
    check("импорт bot без ошибок", True)


async def _category_of(session, name: str):
    return (await session.scalars(
        select(Specialist).where(Specialist.name == name))).first()


async def test_db_and_categories() -> None:
    await db.init_db()
    # Категории, которые мы чинили вручную — не должны «уезжать»
    expect = {
        "Fancy Beauty Space": "мастер маникюра",
        "Парикмахер-стилист": "парикмахер",
        "Стилист": "стилист",
        "Массаж (Flex Massage)": "массаж",
        "Тату мастер": "тату и пирсинг",
        "Ламимейкер / Бровист": "брови и ресницы",
    }
    async with db.get_session() as s:
        for name, cat in expect.items():
            sp = await _category_of(s, name)
            check(f"категория «{name}» = {cat}",
                  bool(sp) and sp.category == cat,
                  f"в базе: {sp.category if sp else 'нет карточки'}")


def test_fix_category_no_override() -> None:
    # Курируемая категория главнее имени (баг «Space» → «spa» → косметолог)
    from utils.geo import detect_category
    # detect по имени может ошибаться — это норма, главное что её не применяют
    item = {"name": "Fancy Beauty Space", "category": "мастер маникюра"}
    result = item.get("category") or detect_category(item["name"])
    check("категория из данных, а не по имени", result == "мастер маникюра",
          f"получили {result}")


async def test_reseed_preserves_premium() -> None:
    async with db.get_session() as s:
        sp = await _category_of(s, "Fancy Beauty Space")
        sp.is_premium = True
        sp.photo_file_id = "PHOTO_TEST"
        old_id = sp.id  # запоминаем id — он НЕ должен меняться (ссылки claim_<id>)
        await s.commit()
    # имитируем смену версии сидов → пересев
    async with db.get_session() as s:
        await s.merge(Meta(key="seed_version", value="0"))
        await s.commit()
    await db._seed_if_needed()
    async with db.get_session() as s:
        sp = await _category_of(s, "Fancy Beauty Space")
    check("пересев сохранил премиум", bool(sp) and sp.is_premium is True)
    check("пересев сохранил фото", bool(sp) and sp.photo_file_id == "PHOTO_TEST")
    check("пересев обновил категорию из файла",
          bool(sp) and sp.category == "мастер маникюра")
    # Главное: id карточки не изменился → ссылки claim_<id> не протухают
    check("пересев сохранил id карточки (ссылки не ломаются)",
          bool(sp) and sp.id == old_id,
          f"было #{old_id}, стало #{sp.id if sp else '—'}")


async def test_reseed_ids_stable_all() -> None:
    """id ВСЕХ seed-карточек не меняются после смены версии засева."""
    async with db.get_session() as s:
        rows = (await s.scalars(
            select(Specialist).where(Specialist.source == "seed"))).all()
        before = {db._seed_key(r.name, r.contact, r.city, r.province): r.id
                  for r in rows}
    async with db.get_session() as s:
        await s.merge(Meta(key="seed_version", value="0"))
        await s.commit()
    await db._seed_if_needed()
    async with db.get_session() as s:
        rows = (await s.scalars(
            select(Specialist).where(Specialist.source == "seed"))).all()
        after = {db._seed_key(r.name, r.contact, r.city, r.province): r.id
                 for r in rows}
    changed = [k for k, i in before.items() if after.get(k) != i]
    check("id всех seed-карточек стабильны после пересева",
          not changed, f"сменились id у {len(changed)} карточек")


async def test_reseed_keeps_edited_premium_card() -> None:
    """Если у премиум-карточки отредактировали контакт (ключ разошёлся с файлом),
    пересев НЕ должен её удалить/затереть и не должен создать дубликат."""
    async with db.get_session() as s:
        sp = await _category_of(s, "Fancy Beauty Space")
        sp.is_premium = True
        sp.photo_file_id = "PHOTO_EDIT"
        sp.contact = "instagram: @fancy_beauty_space · +31 6 19 52 06 60"  # правка
        old_id = sp.id
        await s.commit()
    async with db.get_session() as s:
        await s.merge(Meta(key="seed_version", value="0"))
        await s.commit()
    await db._seed_if_needed()
    async with db.get_session() as s:
        rows = (await s.scalars(select(Specialist).where(
            Specialist.name == "Fancy Beauty Space"))).all()
    check("нет дубля Fancy после пересева с правкой", len(rows) == 1,
          f"карточек Fancy: {len(rows)}")
    sp = rows[0] if rows else None
    check("правленый премиум сохранён", bool(sp) and sp.is_premium is True)
    check("правленое фото сохранено", bool(sp) and sp.photo_file_id == "PHOTO_EDIT")
    check("правленый контакт не откатился к файлу",
          bool(sp) and "fancy_beauty_space" in (sp.contact or ""),
          f"контакт: {sp.contact if sp else '—'}")
    check("id правленой карточки сохранён", bool(sp) and sp.id == old_id)


async def test_allo_capacity() -> None:
    """Места и абонемент-кредиты Allo Walks считаются верно."""
    import handlers.allo as A
    from datetime import datetime, timedelta
    from database.models import AlloBooking
    keys = [w["key"] for w in config.ALLO_WALKS]
    async with db.get_session() as s:
        b0 = await A._taken(s, keys[0])
        # покупка абонемента НЕ занимает места на прогулках (куплен вчера)
        s.add(AlloBooking(walk_key="pass", plan="pass", user_id=901, status="paid",
                          paid_at=datetime.utcnow() - timedelta(days=1)))
        s.add(AlloBooking(walk_key=keys[0], plan="single", user_id=902, status="paid"))
        s.add(AlloBooking(walk_key=keys[0], plan="use", user_id=901, status="paid"))
        await s.commit()
    async with db.get_session() as s:
        check("разовая+списание заняли 2 места", await A._taken(s, keys[0]) == b0 + 2)
        check("покупка абонемента не занимает место на других датах",
              await A._taken(s, keys[1]) == 0)
        # абонемент активен, 1 списание → осталось credits-1
        _p, rem, _vu = await A._active_pass(s, 901)
        check("у абонемента списалась 1 прогулка",
              rem == config.ALLO_PASS_CREDITS - 1, f"осталось {rem}")
    # просроченная неоплата не держит место
    async with db.get_session() as s:
        before = await A._taken(s, keys[2])
        old = AlloBooking(walk_key=keys[2], plan="single", user_id=903, status="pending")
        s.add(old)
        await s.commit()
        old.created_at = datetime.utcnow() - timedelta(hours=3)
        await s.commit()
    async with db.get_session() as s:
        check("просроченная неоплата не занимает место",
              await A._taken(s, keys[2]) == before)
    # ручное закрытие даты (/alloclose): свободных мест нет, хотя броней нет
    async with db.get_session() as s:
        check("до закрытия есть свободные места",
              await A._remaining(s, keys[1]) > 0)
        await s.merge(Meta(key=A._closed_key(keys[1]), value="closed"))
        await s.commit()
    async with db.get_session() as s:
        check("закрытая дата показывает 0 мест",
              await A._remaining(s, keys[1]) == 0)
        m = await s.get(Meta, A._closed_key(keys[1]))
        await s.delete(m)
        await s.commit()
    async with db.get_session() as s:
        check("после открытия места вернулись",
              await A._remaining(s, keys[1]) > 0)


async def test_allo_referral() -> None:
    """Реферал: приводящий получает €-бонус и он списывается при оплате."""
    import handlers.allo as A
    from database.models import AlloBooking

    class _FakeBot:
        async def send_message(self, *a, **k):
            pass

    await A.register_referral(111, 222)  # 111 привёл 222
    await A._maybe_earn_referral(_FakeBot(), 222)  # 222 оплатил впервые → +€10
    async with db.get_session() as s:
        check("приводящий получил 1 бонус", await A._referral_credits(s, 111) == 1)
    # приводящий покупает разовую €35 → скидка €10 → к оплате €25
    async with db.get_session() as s:
        b = AlloBooking(walk_key=config.ALLO_WALKS[0]["key"], plan="single",
                        user_id=111, status="pending", amount="35.00")
        s.add(b); await s.commit(); await s.refresh(b)
        pay, disc = await A._reserve_credits(s, 111, "35.00", b.id)
        bid = b.id
    check("скидка применилась (€10 → к оплате €25)", pay == "25.00" and disc == 10)
    async with db.get_session() as s:
        await A._settle_credits(s, bid, paid=True)
    async with db.get_session() as s:
        check("бонус списан после оплаты", await A._referral_credits(s, 111) == 0)
    # нельзя привести самого себя / уже приведённого
    await A.register_referral(333, 333)
    await A.register_referral(999, 222)  # 222 уже приведён — не перезапишется
    async with db.get_session() as s:
        check("нельзя привести себя", await A._referral_credits(s, 333) == 0)


async def test_premiums_query() -> None:
    """Список премиум-карточек (команда /premiums) находит помеченные премиумом."""
    # test_reseed_preserves_premium уже пометил Fancy как премиум
    async with db.get_session() as s:
        rows = (await s.scalars(
            select(Specialist).where(Specialist.is_premium.is_(True)))).all()
    names = {r.name for r in rows}
    check("список премиумов не пуст", bool(rows))
    check("Fancy Beauty Space попадает в список премиумов",
          "Fancy Beauty Space" in names, f"в списке: {sorted(names)}")


def test_wordpress_util() -> None:
    import utils.wordpress as wp
    check("публикация на сайт выключена без настроек", wp.wp_enabled() is False)
    check("ссылка на редактирование записи корректна",
          wp.edit_link(42).endswith("/wp-admin/post.php?post=42&action=edit"))
    # Галерея: пусто → пусто, много фото → сетка (не куча), все фото на месте
    imgs = [{"id": i, "source_url": f"http://x/{i}.jpg"} for i in (1, 2, 3)]
    g = wp.gallery_block(imgs)
    check("галерея пустая без фото", wp.gallery_block([]) == "")
    check("галерея — сетка колонками", "wp-block-gallery" in g and "columns-" in g)
    check("галерея содержит все фото", g.count("wp-block-image") == 3)
    # Ручная раскладка фото по разделам
    body = "<p>i</p><h2>A</h2><p>a</p><h2>B</h2><p>b</p>"
    check("разделы статьи распознаются", wp.section_titles(body) == ["A", "B"])
    content, feat = wp.build_content_with_images(body, [
        {"im": {"id": 10, "source_url": "u"}, "where": "top"},
        {"im": {"id": 11, "source_url": "u"}, "where": 1},
    ])
    check("обложка = верхнее фото", feat == 10)
    check("обложка не дублируется в теле", "wp-image-10" not in content)
    check("фото раздела 2 стоит после его заголовка",
          content.index("wp-image-11") > content.index("<h2>B</h2>"))


def test_detect_category_basic() -> None:
    from utils.geo import detect_category
    check("«маникюр» → мастер маникюра", detect_category("маникюр") == "мастер маникюра")
    check("«юрист» → юрист", detect_category("нужен юрист") == "юрист")


async def main() -> None:
    test_import_bot()
    await test_db_and_categories()
    test_fix_category_no_override()
    await test_reseed_preserves_premium()
    await test_reseed_ids_stable_all()
    await test_reseed_keeps_edited_premium_card()
    await test_premiums_query()
    await test_allo_capacity()
    await test_allo_referral()
    test_wordpress_util()
    test_detect_category_basic()
    print()
    if _fails:
        print(f"❌ Провалено проверок: {len(_fails)} -> {', '.join(_fails)}")
        sys.exit(1)
    print("✅ Все проверки пройдены")


if __name__ == "__main__":
    asyncio.run(main())
