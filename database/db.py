"""Подключение к базе и создание таблиц."""
import os
from collections import defaultdict

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import config
from database.models import Base, Meta, Specialist

# Движок и фабрика сессий — создаются один раз на всё приложение
engine = create_async_engine(config.DB_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

# Версия засева базы специалистов. Повышай число, когда меняешь данные/логику —
# при следующем запуске бот синхронизирует исходные карточки на месте.
SEED_VERSION = "10"
# В скольких провинциях должна встречаться карточка, чтобы считать её
# «онлайн-специалистом» (работает по всей стране) и хранить одной записью.
ONLINE_PROVINCE_THRESHOLD = 6


# Колонки, которые могли появиться позже (для миграции существующей базы)
_LATER_COLUMNS = {
    "is_online": "BOOLEAN DEFAULT 0",
    "is_premium": "BOOLEAN DEFAULT 0",
    "status": "VARCHAR(20) DEFAULT 'active'",
    "source": "VARCHAR(20) DEFAULT 'seed'",
    "submitter_user_id": "BIGINT",
    "invoice_email": "VARCHAR(200)",
    "paid_until": "DATETIME",
    "payment_id": "VARCHAR(100)",
    "plan": "VARCHAR(10) DEFAULT 'year'",
    "renewal_reminded": "BOOLEAN DEFAULT 0",
    "photo_file_id": "TEXT",
    "premium_until": "DATETIME",
    "referred_by_specialist_id": "INTEGER",
}

# Колонки таблицы пользователей, которые могли появиться позже
_USER_LATER_COLUMNS = {
    "referred_by": "BIGINT",
}

# Колонки таблицы броней рекламы, которые могли появиться позже
_AD_LATER_COLUMNS = {
    "opt": "VARCHAR(20) DEFAULT 'std'",
    "addon": "VARCHAR(20)",
    "dates_csv": "TEXT",
    "client_type": "VARCHAR(20)",
    "buyer_name": "VARCHAR(200)",
    "company": "VARCHAR(200)",
    "btw": "VARCHAR(40)",
    "kvk": "VARCHAR(40)",
    "address": "VARCHAR(300)",
    "postcode": "VARCHAR(20)",
    "phone": "VARCHAR(40)",
}

_DISCOVERED_EVENT_LATER_COLUMNS = {
    "starts_at": "DATETIME",
    "ends_at": "DATETIME",
}


async def init_db() -> None:
    """Создаёт таблицы, добавляет недостающие колонки и засевает специалистов."""
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _migrate()
    await _seed_if_needed()
    await _repair_misclassified_specialists()


async def _repair_misclassified_specialists() -> None:
    """Исправляет очевидные старые ошибки категорий без потери карточек.

    Раньше «химчистка салона» отправляла автомобильный детейлинг в «клининг».
    Кроме того, в базе остались названия категорий из старого справочника,
    которых уже нет в интерфейсе. Контакты, оплата, владелец, фото и остальные
    поля при исправлении остаются нетронутыми.
    """
    from utils.geo import CATEGORIES, detect_category

    legacy_defaults = {
        "музыка": "музыкальные занятия",
        "еда": "продукты и магазины",
        "веб-разработчик": "it и веб",
    }

    async with async_session() as session:
        rows = (await session.scalars(select(Specialist))).all()
        changed = False
        for specialist in rows:
            text = f"{specialist.name} {specialist.description or ''}"
            detected = detect_category(text)
            new_category = None
            if specialist.category == "клининг" and detected == "автосервис":
                new_category = "автосервис"
            elif specialist.category in legacy_defaults:
                new_category = detected or legacy_defaults[specialist.category]
            elif specialist.category == "услуги" and detected in CATEGORIES:
                new_category = detected
            if new_category and new_category != specialist.category:
                specialist.category = new_category
                changed = True
        if changed:
            await session.commit()


async def _migrate() -> None:
    """Добавляет недостающие колонки в таблицу специалистов (без потери данных)."""
    async with engine.begin() as conn:
        def existing_cols(sync_conn) -> set[str]:
            return {c["name"] for c in inspect(sync_conn).get_columns("specialists")}

        cols = await conn.run_sync(existing_cols)
        for name, ddl in _LATER_COLUMNS.items():
            if name not in cols:
                await conn.exec_driver_sql(
                    f"ALTER TABLE specialists ADD COLUMN {name} {ddl}"
                )

        def user_cols(sync_conn) -> set[str]:
            return {c["name"] for c in inspect(sync_conn).get_columns("users")}

        ucols = await conn.run_sync(user_cols)
        for name, ddl in _USER_LATER_COLUMNS.items():
            if name not in ucols:
                await conn.exec_driver_sql(f"ALTER TABLE users ADD COLUMN {name} {ddl}")

        def ad_cols(sync_conn):
            insp = inspect(sync_conn)
            if "ad_bookings" not in insp.get_table_names():
                return None
            return {c["name"] for c in insp.get_columns("ad_bookings")}

        acols = await conn.run_sync(ad_cols)
        if acols is not None:
            for name, ddl in _AD_LATER_COLUMNS.items():
                if name not in acols:
                    await conn.exec_driver_sql(
                        f"ALTER TABLE ad_bookings ADD COLUMN {name} {ddl}"
                    )

        def discovered_event_cols(sync_conn):
            insp = inspect(sync_conn)
            if "discovered_events" not in insp.get_table_names():
                return None
            return {c["name"] for c in insp.get_columns("discovered_events")}

        ecols = await conn.run_sync(discovered_event_cols)
        if ecols is not None:
            for name, ddl in _DISCOVERED_EVENT_LATER_COLUMNS.items():
                if name not in ecols:
                    await conn.exec_driver_sql(
                        f"ALTER TABLE discovered_events ADD COLUMN {name} {ddl}"
                    )


def _seed_key(name: str, contact: str | None, city: str, province: str) -> tuple:
    """Устойчивый ключ карточки гайда — по нему сопоставляем файл и базу."""
    return (
        (name or "").strip().lower(),
        (contact or "").strip().lower(),
        (city or "").strip().lower(),
        (province or "").strip().lower(),
    )


async def _seed_if_needed() -> None:
    """Синхронизирует специалистов из гайда, если версия засева устарела.

    ВАЖНО: карточки НЕ удаляются и не пересоздаются — они обновляются на месте.
    Так у карточки сохраняется её id (а значит и ссылки claim_<id>, которые мы
    рассылаем специалистам, не протухают при обновлении гайда). Раньше пересев
    делал delete+insert, из-за чего id менялись и разосланные ссылки ломались.

    Карточки, добавленные админом и через само-добавление (source != seed),
    НИКОГДА не трогаем — работаем только с source == seed.
    """
    async with async_session() as session:
        version = await session.get(Meta, "seed_version")
        if version is not None and version.value == SEED_VERSION:
            return  # актуальная версия уже залита

    await _sync_seed_cards()

    async with async_session() as session:
        await session.merge(Meta(key="seed_version", value=SEED_VERSION))
        await session.commit()


def _desired_seed_rows() -> list[dict]:
    """Готовит карточки из файла гайда, схлопывая дубликаты онлайн-специалистов.

    Один человек (имя + контакт), размещённый сразу во многих провинциях, — это
    онлайн-специалист: храним его ОДНОЙ карточкой с пометкой is_online. Остальных
    (локальных) сохраняем по карточке на провинцию. Возвращает список словарей
    (без записи в базу) — их дальше сопоставляем с существующими по ключу.
    """
    from seeds.specialists_seed import SEED_SPECIALISTS
    from utils.geo import detect_category, province_of_city

    def _fix_category(item: dict) -> str:
        """Категория из данных (курируемая) — главная. Определение по имени —
        только если категория не задана.

        Раньше имя переопределяло категорию, но detect_category матчит по
        подстроке и ошибается на брендах (напр. «Space» → «spa» → косметолог).
        Поэтому доверяем тому, что прописано в карточке.
        """
        return item.get("category") or detect_category(item["name"])

    # Группируем карточки по человеку (имя + контакт)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in SEED_SPECIALISTS:
        key = (item["name"].strip().lower(), (item.get("contact") or "").strip().lower())
        groups[key].append(item)

    rows: list[dict] = []
    for items in groups.values():
        provinces = {
            (it.get("province") or "").strip()
            for it in items
            if (it.get("province") or "").strip()
        }
        base = items[0]
        if len(provinces) >= ONLINE_PROVINCE_THRESHOLD:
            # Онлайн-специалист — одна карточка без привязки к городу/провинции
            rows.append({
                "name": base["name"],
                "category": _fix_category(base),
                "city": "",
                "province": "",
                "description": base.get("description"),
                "contact": base.get("contact"),
                "is_online": True,
            })
        else:
            # Локальные специалисты — сохраняем каждую карточку
            for it in items:
                province = (
                    (it.get("province") or "").strip()
                    or province_of_city(it.get("city", ""))
                    or ""
                )
                rows.append({
                    "name": it["name"],
                    "category": _fix_category(it),
                    "city": it.get("city", ""),
                    "province": province,
                    "description": it.get("description"),
                    "contact": it.get("contact"),
                    "is_online": False,
                })
    return rows


def _has_live_data(r: Specialist) -> bool:
    """Есть ли у карточки «нажитое»: премиум, фото, оплата или владелец.

    Такие карточки курировал админ или за них платил специалист — их НЕЛЬЗЯ
    удалять/пересоздавать при пересеве, даже если админ отредактировал контакт/
    имя/город (из-за чего ключ перестал совпадать с файлом гайда).
    """
    return bool(r.is_premium or r.photo_file_id or r.paid_until
                or r.submitter_user_id)


async def _sync_seed_cards() -> None:
    """Обновляет карточки гайда НА МЕСТЕ (id сохраняются): обновляет существующие,
    добавляет новые, удаляет пропавшие из файла. «Живые» атрибуты (премиум, фото,
    оплата, владелец) и id не трогаем — их задаёт бот.

    ВАЖНО: карточку с «нажитым» (премиум/фото/оплата/владелец) НИКОГДА не удаляем,
    даже если админ отредактировал у неё контакт/имя (тогда ключ разошёлся с
    файлом). Иначе пересев затирал бы премиум и ручные правки — что и случалось.
    """
    desired: dict[tuple, dict] = {}
    for d in _desired_seed_rows():
        desired.setdefault(
            _seed_key(d["name"], d["contact"], d["city"], d["province"]), d)

    # Индекс желаемых карточек по имени — чтобы сопоставить отредактированную
    # «живую» карточку с записью из файла и не создать дубликат.
    desired_by_name: dict[str, list[tuple]] = defaultdict(list)
    for key, d in desired.items():
        desired_by_name[d["name"].strip().lower()].append(key)

    async with async_session() as session:
        existing_rows = (await session.scalars(
            select(Specialist).where(Specialist.source == "seed"))).all()
        existing: dict[tuple, Specialist] = {}
        for r in existing_rows:
            existing.setdefault(_seed_key(r.name, r.contact, r.city, r.province), r)

        handled: set[tuple] = set()

        # 1. Точное совпадение по ключу — обновляем редакционные поля из файла
        for key, d in desired.items():
            row = existing.get(key)
            if row is not None:
                row.category = d["category"]
                row.description = d["description"]
                row.is_online = d["is_online"]
                handled.add(key)

        # 2. Оставшиеся существующие карточки (ключ разошёлся с файлом)
        for key, row in existing.items():
            if key in desired:
                continue
            if _has_live_data(row):
                # Курируемая/оплаченная/отредактированная — НЕ трогаем.
                # Гасим соответствующую запись из файла по имени, чтобы не дублировать.
                for dk in desired_by_name.get(row.name.strip().lower(), []):
                    handled.add(dk)
            else:
                await session.delete(row)  # чистая карточка, убранная из файла

        # 3. Добавляем то, чего ещё нет
        for key, d in desired.items():
            if key in handled or key in existing:
                continue
            session.add(Specialist(
                name=d["name"], category=d["category"], city=d["city"],
                province=d["province"], description=d["description"],
                contact=d["contact"], is_online=d["is_online"], source="seed",
            ))

        await session.commit()


def get_session() -> AsyncSession:
    """Возвращает новую сессию для работы с базой."""
    return async_session()
