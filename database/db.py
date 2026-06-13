"""Подключение к базе и создание таблиц."""
import os
from collections import defaultdict

from sqlalchemy import delete, inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import config
from database.models import Base, Meta, Specialist

# Движок и фабрика сессий — создаются один раз на всё приложение
engine = create_async_engine(config.DB_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

# Версия засева базы специалистов. Повышай число, когда меняешь данные/логику —
# при следующем запуске бот пересоздаст таблицу специалистов заново.
SEED_VERSION = "5"
# В скольких провинциях должна встречаться карточка, чтобы считать её
# «онлайн-специалистом» (работает по всей стране) и хранить одной записью.
ONLINE_PROVINCE_THRESHOLD = 6


# Колонки, которые могли появиться позже (для миграции существующей базы)
_LATER_COLUMNS = {
    "is_online": "BOOLEAN DEFAULT 0",
    "status": "VARCHAR(20) DEFAULT 'active'",
    "source": "VARCHAR(20) DEFAULT 'seed'",
    "submitter_user_id": "BIGINT",
    "paid_until": "DATETIME",
    "payment_id": "VARCHAR(100)",
    "plan": "VARCHAR(10) DEFAULT 'year'",
    "renewal_reminded": "BOOLEAN DEFAULT 0",
}


async def init_db() -> None:
    """Создаёт таблицы, добавляет недостающие колонки и засевает специалистов."""
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _migrate()
    await _seed_if_needed()


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


async def _seed_if_needed() -> None:
    """Засевает специалистов из гайда, если версия засева устарела.

    Карточки, добавленные админом и через само-добавление (source != seed),
    НИКОГДА не трогаем — обновляем только данные из гайда.
    """
    async with async_session() as session:
        version = await session.get(Meta, "seed_version")
        if version is not None and version.value == SEED_VERSION:
            return  # актуальная версия уже залита
        # Удаляем только старые seed-карточки, платные/ручные сохраняем
        await session.execute(delete(Specialist).where(Specialist.source == "seed"))
        await session.commit()

    await _seed_specialists()

    async with async_session() as session:
        await session.merge(Meta(key="seed_version", value=SEED_VERSION))
        await session.commit()


async def _seed_specialists() -> None:
    """Заливает специалистов из гайда, схлопывая дубликаты онлайн-специалистов.

    Один человек (имя + контакт), размещённый сразу во многих провинциях, — это
    онлайн-специалист: храним его ОДНОЙ карточкой с пометкой is_online. Остальных
    (локальных) сохраняем как есть.
    """
    from seeds.specialists_seed import SEED_SPECIALISTS
    from utils.geo import province_of_city

    # Группируем карточки по человеку (имя + контакт)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in SEED_SPECIALISTS:
        key = (item["name"].strip().lower(), (item.get("contact") or "").strip().lower())
        groups[key].append(item)

    rows: list[Specialist] = []
    for items in groups.values():
        provinces = {
            (it.get("province") or "").strip()
            for it in items
            if (it.get("province") or "").strip()
        }
        base = items[0]
        if len(provinces) >= ONLINE_PROVINCE_THRESHOLD:
            # Онлайн-специалист — одна карточка без привязки к городу/провинции
            rows.append(
                Specialist(
                    name=base["name"],
                    category=base["category"],
                    city="",
                    province="",
                    description=base.get("description"),
                    contact=base.get("contact"),
                    is_online=True,
                )
            )
        else:
            # Локальные специалисты — сохраняем каждую карточку
            for it in items:
                province = (
                    (it.get("province") or "").strip()
                    or province_of_city(it.get("city", ""))
                    or ""
                )
                rows.append(
                    Specialist(
                        name=it["name"],
                        category=it["category"],
                        city=it.get("city", ""),
                        province=province,
                        description=it.get("description"),
                        contact=it.get("contact"),
                        is_online=False,
                    )
                )

    async with async_session() as session:
        session.add_all(rows)
        await session.commit()


def get_session() -> AsyncSession:
    """Возвращает новую сессию для работы с базой."""
    return async_session()
