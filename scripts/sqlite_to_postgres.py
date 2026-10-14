"""Перенос базы бота из SQLite (data/bot.db) в PostgreSQL.

Как переезжать на Railway:
1. Добавить в проект сервис PostgreSQL.
2. В сервисе бота на время переноса остановить бота, чтобы в SQLite ничего не писалось.
3. Запустить перенос (в оболочке сервиса бота, где лежит том с data/bot.db):
       python scripts/sqlite_to_postgres.py --target "$POSTGRES_URL"
   Сначала можно проверить без записи: добавить --dry-run.
4. В переменных бота задать DATABASE_URL=${{Postgres.DATABASE_URL}} и перезапустить.
   SQLite-файл остаётся на томе как резервная копия; вернуться назад — убрать DATABASE_URL.

Что делает скрипт:
- доводит SQLite до текущей схемы (те же миграции, что при старте бота);
- создаёт таблицы в PostgreSQL; целевая база должна быть пустой (иначе --force);
- копирует все таблицы в порядке зависимостей пачками, сохраняя id;
- строки длиннее VARCHAR(n) подрезает и сообщает об этом (SQLite длину не проверял);
- выставляет счётчики id (sequence) после копирования, сверяет число строк.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import DateTime, Enum, Integer, String, func, inspect, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

import config  # noqa: E402

# Все модули, где объявлены таблицы, — чтобы схема была полной
import database.models  # noqa: E402,F401
import database.ig_sales_models  # noqa: E402,F401
import database.anonymous_questions  # noqa: E402,F401
import database.ad_sales_models  # noqa: E402,F401
import calendar_shop_runtime  # noqa: E402,F401
import ad_season_campaign_runtime  # noqa: E402,F401
import am_reviews  # noqa: E402,F401
import ad_campaign_guide_runtime  # noqa: E402,F401
from database import db  # noqa: E402
from database.models import Base  # noqa: E402

BATCH = 500


def _fix_row(table, row: dict, cut: dict) -> dict:
    for col in table.columns:
        v = row.get(col.name)
        if v is None:
            continue
        t = col.type
        if isinstance(t, String) and not isinstance(t, Enum) and t.length and isinstance(v, str) and len(v) > t.length:
            row[col.name] = v[:t.length]
            cut[f"{table.name}.{col.name}"] = cut.get(f"{table.name}.{col.name}", 0) + 1
        elif isinstance(t, DateTime) and t.timezone and getattr(v, "tzinfo", 1) is None:
            row[col.name] = v.replace(tzinfo=timezone.utc)   # SQLite отдаёт без зоны, а это UTC
    return row


async def run(sqlite_path: str, target_url: str, dry_run: bool, force: bool) -> int:
    target_url = config._db_url(target_url)
    if not target_url.startswith("postgresql+asyncpg://"):
        print("Нужен адрес PostgreSQL: --target postgresql://… или переменная POSTGRES_URL")
        return 2
    if not Path(sqlite_path).exists():
        print(f"Нет файла SQLite: {sqlite_path}")
        return 2
    src = create_async_engine(f"sqlite+aiosqlite:///{sqlite_path}")
    dst = create_async_engine(target_url, connect_args={"server_settings": {"timezone": "UTC"}})

    # 1. SQLite → текущая схема (как при старте бота)
    db_engine = db.engine
    db.engine = src
    try:
        async with src.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await db._migrate()
    finally:
        db.engine = db_engine

    async with src.connect() as conn:
        src_tables = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
    known = set(Base.metadata.tables)
    extra = sorted(src_tables - known)
    if extra:
        print("Пропускаю таблицы без модели (резервные/устаревшие):", ", ".join(extra))

    # 2. Целевая база: таблицы и проверка, что она пустая
    async with dst.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        filled = []
        for table in Base.metadata.sorted_tables:
            n = await conn.scalar(select(func.count()).select_from(table))
            if n:
                filled.append(f"{table.name}={n}")
    if filled and not force:
        print("В PostgreSQL уже есть данные:", ", ".join(filled[:10]), "… Остановлено (флаг --force — перезаписать).")
        await src.dispose()
        await dst.dispose()
        return 3

    # 3. Копирование
    cut: dict[str, int] = {}
    report = []
    async with src.connect() as s, dst.begin() as d:
        if filled and force:
            for table in reversed(Base.metadata.sorted_tables):
                await d.execute(table.delete())
        for table in Base.metadata.sorted_tables:
            if table.name not in src_tables:
                report.append((table.name, 0, 0))
                continue
            src_cols = {c["name"] for c in await s.run_sync(lambda c, t=table.name: inspect(c).get_columns(t))}
            cols = [c for c in table.columns if c.name in src_cols]
            total = 0
            result = await s.stream(select(*cols))
            async for part in result.partitions(BATCH):
                rows = [_fix_row(table, dict(r._mapping), cut) for r in part]
                if not dry_run:
                    await d.execute(table.insert(), rows)
                total += len(rows)
            copied = total if dry_run else await d.scalar(select(func.count()).select_from(table))
            report.append((table.name, total, copied))
        # 4. Счётчики id
        if not dry_run:
            for table in Base.metadata.sorted_tables:
                pk = list(table.primary_key.columns)
                if len(pk) == 1 and isinstance(pk[0].type, Integer) and pk[0].autoincrement in (True, "auto"):
                    seq = await d.scalar(text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": table.name, "c": pk[0].name})
                    if seq:
                        await d.execute(text(f"SELECT setval('{seq}', COALESCE((SELECT MAX({pk[0].name}) FROM {table.name}), 1), "
                                             f"(SELECT MAX({pk[0].name}) FROM {table.name}) IS NOT NULL)"))
        if dry_run:
            await d.rollback()

    bad = [(n, a, b) for n, a, b in report if a != b]
    for name, a, b in report:
        if a or b:
            print(f"  {name:40} {a:>8} → {b:>8}")
    if cut:
        print("Подрезаны слишком длинные значения:", ", ".join(f"{k} ×{v}" for k, v in sorted(cut.items())))
    print(("Проверка без записи завершена." if dry_run else "Перенос завершён.")
          + f" Таблиц: {sum(1 for _, a, _ in report if a)}, строк: {sum(a for _, a, _ in report)}.")
    await src.dispose()
    await dst.dispose()
    if bad and not dry_run:
        print("НЕ СОШЛОСЬ число строк:", bad)
        return 4
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sqlite", default=config.DB_PATH, help="путь к bot.db (по умолчанию data/bot.db)")
    ap.add_argument("--target", default=os.getenv("POSTGRES_URL", ""), help="адрес PostgreSQL (или POSTGRES_URL)")
    ap.add_argument("--dry-run", action="store_true", help="прочитать и проверить всё, ничего не записывая")
    ap.add_argument("--force", action="store_true", help="очистить непустую целевую базу перед переносом")
    a = ap.parse_args()
    raise SystemExit(asyncio.run(run(a.sqlite, a.target, a.dry_run, a.force)))


if __name__ == "__main__":
    main()
