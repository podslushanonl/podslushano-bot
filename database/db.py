"""Подключение к базе и создание таблиц."""
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import config
from database.models import Base, Specialist

# Движок и фабрика сессий — создаются один раз на всё приложение
engine = create_async_engine(config.DB_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Создаёт таблицы (если их нет) и наполняет базу примерами специалистов."""
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _seed_specialists()


async def _seed_specialists() -> None:
    """Заливает тестовых специалистов, только если таблица пустая.

    Реальные данные с сайта заменят эти примеры позже.
    """
    from seeds.specialists_seed import SEED_SPECIALISTS
    from utils.geo import province_of_city

    async with async_session() as session:
        existing = await session.scalar(select(Specialist).limit(1))
        if existing is not None:
            return  # данные уже есть — ничего не делаем

        for item in SEED_SPECIALISTS:
            # Провинцию берём явно из данных (специалисты в гайде сгруппированы
            # по провинциям); если её нет — пытаемся вычислить по городу.
            province = item.get("province") or province_of_city(item.get("city", "")) or ""
            session.add(
                Specialist(
                    name=item["name"],
                    category=item["category"],
                    city=item.get("city", ""),
                    province=province,
                    description=item.get("description"),
                    contact=item.get("contact"),
                )
            )
        await session.commit()


def get_session() -> AsyncSession:
    """Возвращает новую сессию для работы с базой."""
    return async_session()
