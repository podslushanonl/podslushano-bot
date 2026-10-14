"""Подключение к базе и создание таблиц."""
import os
from collections import defaultdict

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import config
from database.models import Base, Meta, Specialist

# Движок и фабрика сессий — создаются один раз на всё приложение
# SQLite (файл data/bot.db) по умолчанию; PostgreSQL — если задан DATABASE_URL (см. config.DB_URL)
engine = create_async_engine(
    config.DB_URL, echo=False,
    # PostgreSQL: время сессии в UTC — как и везде в коде (naive UTC); иначе func.now() сдвинется
    **({} if config.DB_URL.startswith("sqlite") else {
        "pool_pre_ping": True, "pool_size": 10, "max_overflow": 10,
        "connect_args": {"server_settings": {"timezone": "UTC"}}}),
)
async_session = async_sessionmaker(engine, expire_on_commit=False)

# Версия засева базы специалистов. Повышай число, когда меняешь данные/логику —
# при следующем запуске бот синхронизирует исходные карточки на месте.
SEED_VERSION = "10"
# В скольких провинциях должна встречаться карточка, чтобы считать её
# «онлайн-специалистом» (работает по всей стране) и хранить одной записью.
ONLINE_PROVINCE_THRESHOLD = 6


# Колонки, которые могли появиться позже (для миграции существующей базы)
_LATER_COLUMNS = {
    "is_online": "BOOLEAN DEFAULT FALSE",
    "is_premium": "BOOLEAN DEFAULT FALSE",
    "status": "VARCHAR(20) DEFAULT 'active'",
    "source": "VARCHAR(20) DEFAULT 'seed'",
    "submitter_user_id": "BIGINT",
    "invoice_email": "VARCHAR(200)",
    "paid_until": "TIMESTAMP",
    "payment_id": "VARCHAR(100)",
    "plan": "VARCHAR(10) DEFAULT 'year'",
    "renewal_reminded": "BOOLEAN DEFAULT FALSE",
    "photo_file_id": "TEXT",
    "premium_until": "TIMESTAMP",
    "referred_by_specialist_id": "INTEGER",
    "card_color": "VARCHAR(10)",
}

# Колонки таблицы пользователей, которые могли появиться позже
_USER_LATER_COLUMNS = {
    "referred_by": "BIGINT",
}

_SUBMISSION_LATER_COLUMNS = {
    "details": "TEXT",
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
    "amount": "VARCHAR(20)",
    "materials_status": "VARCHAR(20) DEFAULT 'waiting'",
}

_DISCOVERED_EVENT_LATER_COLUMNS = {
    "starts_at": "TIMESTAMP",
    "ends_at": "TIMESTAMP",
    "section_key": "VARCHAR(24) DEFAULT 'nearby'",
    "source_url": "VARCHAR(700) DEFAULT ''",
    "ticket_url": "VARCHAR(700) DEFAULT ''",
    "photo_url": "VARCHAR(1000) DEFAULT ''",
    "territory": "VARCHAR(100) DEFAULT 'Nederland'",
}

_EVENT_LISTING_LATER_COLUMNS = {
    "starts_at": "TIMESTAMP",
    "ends_at": "TIMESTAMP",
    "event_time": "VARCHAR(40)",
    "venue": "VARCHAR(200)",
    "category": "VARCHAR(40)",
    "source": "VARCHAR(10)",
}

_ALLO_SALE_LATER_COLUMNS = {
    "send_on": "VARCHAR(10)",
}

_LISTING_LATER_COLUMNS = {
    "intent": "VARCHAR(20)",
    "app_user_id": "INTEGER",
    "photos": "TEXT",
}

# Аккаунты приложения: правила сообщества и бан (чаты, посты)
_HIDDEN_LATER_TABLES = ("chat_messages", "user_posts")   # колонка hidden (модерация) появилась позже

_APP_USER_LATER_COLUMNS = {
    "rules_at": "TIMESTAMP",
    "banned_until": "TIMESTAMP",
    "country": "VARCHAR(20) NOT NULL DEFAULT 'Нидерланды'",
}
_USER_POST_LATER_COLUMNS = {
    "country": "VARCHAR(20) NOT NULL DEFAULT 'Нидерланды'",
    "repost_of": "INTEGER",
    "photo_count": "INTEGER NOT NULL DEFAULT 0",
}
_COUNTRY_VALUES = "('Нидерланды', 'Германия', 'Бельгия')"


async def init_db() -> None:
    """Создаёт таблицы, добавляет недостающие колонки и засевает специалистов."""
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    await _widen_meta_key()
    await _import_sqlite_once()
    await _repair_long_meta_keys_once()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _migrate()
    await _seed_if_needed()
    await _repair_misclassified_specialists()


SQLITE_IMPORTED_KEY = "sqlite_imported_at"
META_KEYS_REPAIRED = "meta_long_keys_repaired"


async def _widen_meta_key() -> None:
    """meta.key был VARCHAR(50): в PostgreSQL длинные ключи-отметки не помещались. Расширяем до 255."""
    if config.DB_URL.startswith("sqlite"):
        return   # SQLite длину не проверяет
    async with engine.begin() as conn:
        cols = await conn.run_sync(lambda c: {x["name"]: x for x in inspect(c).get_columns("meta")}
                                   if "meta" in inspect(c).get_table_names() else {})
        length = getattr(cols.get("key", {}).get("type"), "length", None)
        if length and length < 255:
            await conn.exec_driver_sql("ALTER TABLE meta ALTER COLUMN key TYPE VARCHAR(255)")


async def _repair_long_meta_keys_once() -> None:
    """Первый перенос подрезал ключи meta до 50 символов (96 записей не вошли, 9 легли с обрезанным
    ключом). Один раз дозагружаем такие записи из SQLite с полными ключами и убираем обрезки."""
    if config.DB_URL.startswith("sqlite") or not os.path.exists(config.DB_PATH):
        return
    import logging
    import sqlite3
    log = logging.getLogger(__name__)
    async with async_session() as session:
        if not await session.get(Meta, SQLITE_IMPORTED_KEY) or await session.get(Meta, META_KEYS_REPAIRED):
            return
        with sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True) as src:
            rows = src.execute("SELECT key, value FROM meta WHERE length(key) > 50").fetchall()
            short = {r[0] for r in src.execute("SELECT key FROM meta WHERE length(key) <= 50")}
        restored = 0
        for key, value in rows:
            if not await session.get(Meta, key):
                session.add(Meta(key=key, value=(value or "").replace("\x00", "")))
                restored += 1
            cut = key[:50]
            if cut not in short:
                junk = await session.get(Meta, cut)
                if junk:
                    await session.delete(junk)
        session.add(Meta(key=META_KEYS_REPAIRED, value=str(restored)))
        await session.commit()
    log.warning("meta: восстановлено %s записей с длинными ключами", restored)


async def _import_sqlite_once() -> None:
    """Переезд на PostgreSQL без консоли: при SQLITE_IMPORT=1 (или force) бот при старте сам переносит
    данные из data/bot.db в пустую базу PostgreSQL (scripts/sqlite_to_postgres.py) и ставит
    отметку в meta — повторно не переносит. Ошибка переноса останавливает запуск (всё в одной
    транзакции, база остаётся пустой), чтобы бот не заработал с половиной данных."""
    mode = os.getenv("SQLITE_IMPORT", "").strip().lower()
    if config.DB_URL.startswith("sqlite") or mode not in ("1", "force"):
        return
    import logging
    log = logging.getLogger(__name__)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as session:
        if await session.get(Meta, SQLITE_IMPORTED_KEY):
            log.info("SQLite уже перенесён в PostgreSQL — SQLITE_IMPORT можно убрать")
            return
    if not os.path.exists(config.DB_PATH):
        log.warning("SQLITE_IMPORT=1, но файла %s нет — переносить нечего", config.DB_PATH)
        return
    from scripts.sqlite_to_postgres import run
    log.warning("Переношу данные из %s в PostgreSQL…", config.DB_PATH)
    # force — PostgreSQL очищается перед переносом (например, после неудачной попытки,
    # когда бот успел поработать на пустой базе)
    code = await run(config.DB_PATH, config.DB_URL, dry_run=False, force=mode == "force")
    if code == 3:
        raise RuntimeError("В PostgreSQL уже есть данные, а переноса ещё не было. Чтобы перенести "
                           "заново с очисткой PostgreSQL, задайте SQLITE_IMPORT=force")
    if code != 0:
        raise RuntimeError(f"Перенос SQLite → PostgreSQL не удался (код {code}), см. лог выше")
    from datetime import datetime, timezone
    async with async_session() as session:
        await session.merge(Meta(key=SQLITE_IMPORTED_KEY, value=datetime.now(timezone.utc).isoformat()))
        await session.commit()
    log.warning("Перенос в PostgreSQL завершён")


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
        def submission_cols(sync_conn):
            insp = inspect(sync_conn)
            if "submissions" not in insp.get_table_names():
                return None
            return {c["name"] for c in insp.get_columns("submissions")}

        scols = await conn.run_sync(submission_cols)
        if scols is not None:
            for name, ddl in _SUBMISSION_LATER_COLUMNS.items():
                if name not in scols:
                    await conn.exec_driver_sql(
                        f"ALTER TABLE submissions ADD COLUMN {name} {ddl}"
                    )

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

        def event_listing_cols(sync_conn):
            insp = inspect(sync_conn)
            if "event_listings" not in insp.get_table_names():
                return None
            return {c["name"] for c in insp.get_columns("event_listings")}

        lcols = await conn.run_sync(event_listing_cols)
        if lcols is not None:
            for name, ddl in _EVENT_LISTING_LATER_COLUMNS.items():
                if name not in lcols:
                    await conn.exec_driver_sql(
                        f"ALTER TABLE event_listings ADD COLUMN {name} {ddl}"
                    )

        def listing_cols(sync_conn):
            insp = inspect(sync_conn)
            if "listings" not in insp.get_table_names():
                return None
            return {c["name"] for c in insp.get_columns("listings")}

        board_cols = await conn.run_sync(listing_cols)
        if board_cols is not None:
            for name, ddl in _LISTING_LATER_COLUMNS.items():
                if name not in board_cols:
                    await conn.exec_driver_sql(
                        f"ALTER TABLE listings ADD COLUMN {name} {ddl}"
                    )

        def app_user_cols(sync_conn):
            insp = inspect(sync_conn)
            if "app_users" not in insp.get_table_names():
                return None
            return {c["name"] for c in insp.get_columns("app_users")}

        for table in _HIDDEN_LATER_TABLES:
            def tcols(sync_conn, t=table):
                insp = inspect(sync_conn)
                return {c["name"] for c in insp.get_columns(t)} if t in insp.get_table_names() else None

            cols = await conn.run_sync(tcols)
            if cols is not None and "hidden" not in cols:
                await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN hidden BOOLEAN DEFAULT FALSE")
                # Раньше автоскрытие по жалобам ставило deleted=1. Такие записи (3+ разных жалобы
                # без решения модератора) переносим в hidden, чтобы «Оставить» могло их вернуть.
                if await conn.run_sync(lambda c: "content_reports" in inspect(c).get_table_names()):
                    kind = "msg" if table == "chat_messages" else "post"
                    await conn.exec_driver_sql(
                        f"UPDATE {table} SET hidden = TRUE, deleted = FALSE WHERE deleted = TRUE AND ("
                        f"SELECT COUNT(DISTINCT reporter_id) FROM content_reports r "
                        f"WHERE r.kind = '{kind}' AND r.target_id = {table}.id AND r.resolved = '') >= 3"
                    )

        au_cols = await conn.run_sync(app_user_cols)
        if au_cols is not None:
            for name, ddl in _APP_USER_LATER_COLUMNS.items():
                if name not in au_cols:
                    await conn.exec_driver_sql(f"ALTER TABLE app_users ADD COLUMN {name} {ddl}")
            # Индекс страны: таблица в PostgreSQL создана до него, create_all его уже не добавит
            await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_app_users_country ON app_users (country)")

        # Посты: страна (лента «Рядом»), репосты, число фото — появились в этапе 2
        up_cols = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("user_posts")}
                                      if "user_posts" in inspect(c).get_table_names() else None)
        if up_cols is not None:
            for name, ddl in _USER_POST_LATER_COLUMNS.items():
                if name not in up_cols:
                    await conn.exec_driver_sql(f"ALTER TABLE user_posts ADD COLUMN {name} {ddl}")
            await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_user_posts_country ON user_posts (country)")
            await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_user_posts_repost_of ON user_posts (repost_of)")

        tables = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        # Комнаты чатов: раньше страна хранилась кодом NL — теперь русским названием (или пусто для общей)
        if "chat_rooms" in tables:
            await conn.exec_driver_sql(
                f"UPDATE chat_rooms SET country = 'Нидерланды' WHERE country NOT IN {_COUNTRY_VALUES}")
        # Блокировки переехали в friendships (статус blocked); старую таблицу сохраняем под другим именем
        if "user_blocks" in tables and "friendships" in tables:
            await conn.exec_driver_sql(
                "INSERT INTO friendships (user_id, friend_id, status, created_at, updated_at) "
                "SELECT DISTINCT b.user_id, b.blocked_id, 'blocked', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
                "FROM user_blocks b WHERE b.user_id <> b.blocked_id "
                "AND EXISTS (SELECT 1 FROM app_users u WHERE u.id = b.user_id) "
                "AND EXISTS (SELECT 1 FROM app_users u WHERE u.id = b.blocked_id) "
                "AND NOT EXISTS (SELECT 1 FROM friendships f WHERE f.user_id = b.user_id AND f.friend_id = b.blocked_id)")
            await conn.exec_driver_sql("ALTER TABLE user_blocks RENAME TO user_blocks_migrated")

        def allo_sale_cols(sync_conn):
            insp = inspect(sync_conn)
            if "allo_web_sales" not in insp.get_table_names():
                return None
            return {c["name"] for c in insp.get_columns("allo_web_sales")}

        sale_cols = await conn.run_sync(allo_sale_cols)
        if sale_cols is not None:
            for name, ddl in _ALLO_SALE_LATER_COLUMNS.items():
                if name not in sale_cols:
                    await conn.exec_driver_sql(
                        f"ALTER TABLE allo_web_sales ADD COLUMN {name} {ddl}"
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


def dialect_insert(model):
    """INSERT с поддержкой .on_conflict_do_nothing(...) для текущей базы (SQLite или PostgreSQL)."""
    if config.DB_URL.startswith("postgresql"):
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(model)


def get_session() -> AsyncSession:
    """Возвращает новую сессию для работы с базой."""
    return async_session()
