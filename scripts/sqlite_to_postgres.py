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
  в режиме --dry-run — на временной копии файла, а в PostgreSQL ничего не создаёт и не пишет;
- создаёт таблицы в PostgreSQL; целевая база должна быть пустой (иначе --force);
- копирует все таблицы в порядке зависимостей пачками, сохраняя id;
- строки длиннее VARCHAR(n) подрезает и сообщает об этом (SQLite длину не проверял);
- выставляет счётчики id (sequence) после копирования, сверяет число строк.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
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
        if isinstance(v, str) and "\x00" in v:   # PostgreSQL не принимает нулевой символ в тексте
            v = row[col.name] = v.replace("\x00", "")
            cut[f"{table.name}.{col.name} (\\x00)"] = cut.get(f"{table.name}.{col.name} (\\x00)", 0) + 1
        if (isinstance(t, String) and not isinstance(t, Enum) and t.length and isinstance(v, str) and len(v) > t.length
                and not (col.primary_key or col.unique)):   # ключи не подрезаем — совпадут
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
    tmp = None
    if dry_run:
        # Проверка без записи: миграции гоняем на копии SQLite, исходный файл не трогаем
        tmp = tempfile.TemporaryDirectory()
        copy = str(Path(tmp.name) / "bot.db")
        with sqlite3.connect(sqlite_path) as a, sqlite3.connect(copy) as b:
            a.backup(b)
        sqlite_path = copy
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

    # 2. Целевая база: таблицы (кроме --dry-run) и проверка, что она пустая
    if not dry_run:
        async with dst.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with dst.connect() as conn:
        dst_tables = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        filled = []
        for table in Base.metadata.sorted_tables:
            n = await conn.scalar(select(func.count()).select_from(table)) if table.name in dst_tables else 0
            if n:
                filled.append(f"{table.name}={n}")
    if filled and not force:
        print("В PostgreSQL уже есть данные:", ", ".join(filled[:10]), "… Остановлено (флаг --force — перезаписать).")
        await src.dispose()
        await dst.dispose()
        if tmp:
            tmp.cleanup()
        return 3

    # 3. Копирование. Строки читаем «как есть» и переводим в типы модели сами: строку, которую
    # не удаётся прочитать или которую не принимает PostgreSQL, пропускаем и сохраняем в файл,
    # а не роняем весь перенос (каждая пачка — в своей точке сохранения внутри общей транзакции).
    cut: dict[str, int] = {}
    report = []
    skipped: list[dict] = []
    sdialect = src.dialect

    def _skip(table, row, err) -> None:
        skipped.append({"table": table.name, "error": str(err)[:300],
                        "row": {k: (v if isinstance(v, (int, float, str, type(None))) else str(v)) for k, v in row.items()}})

    async with src.connect() as s, (dst.connect() if dry_run else dst.begin()) as d:
        if filled and force and not dry_run:
            for table in reversed(Base.metadata.sorted_tables):
                await d.execute(table.delete())
        for table in Base.metadata.sorted_tables:
            if table.name not in src_tables:
                report.append((table.name, 0, 0, 0))
                continue
            src_cols = {c["name"] for c in await s.run_sync(lambda c, t=table.name: inspect(c).get_columns(t))}
            cols = [c for c in table.columns if c.name in src_cols]
            procs = {c.name: c.type.dialect_impl(sdialect).result_processor(sdialect, None) for c in cols}
            names = ", ".join(f'"{c.name}"' for c in cols)
            total = lost = 0
            result = await s.stream(text(f'SELECT {names} FROM "{table.name}"'))
            async for part in result.partitions(BATCH):
                rows = []
                for raw in part:
                    row = dict(zip([c.name for c in cols], raw))
                    try:
                        row = {k: (procs[k](v) if procs[k] and v is not None else v) for k, v in row.items()}
                    except Exception as e:  # noqa: BLE001 — битое значение в SQLite
                        _skip(table, row, e)
                        lost += 1
                        continue
                    rows.append(_fix_row(table, row, cut))
                total += len(part)
                if dry_run or not rows:
                    continue
                try:
                    async with d.begin_nested():
                        await d.execute(table.insert(), rows)
                except Exception:  # noqa: BLE001 — ищем, какая строка мешает
                    for row in rows:
                        try:
                            async with d.begin_nested():
                                await d.execute(table.insert(), [row])
                        except Exception as e:  # noqa: BLE001
                            _skip(table, row, e)
                            lost += 1
            copied = total - lost if dry_run else await d.scalar(select(func.count()).select_from(table))
            report.append((table.name, total, copied, lost))
        # 4. Счётчики id
        if not dry_run:
            for table in Base.metadata.sorted_tables:
                pk = list(table.primary_key.columns)
                if len(pk) == 1 and isinstance(pk[0].type, Integer) and pk[0].autoincrement in (True, "auto"):
                    seq = await d.scalar(text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": table.name, "c": pk[0].name})
                    if seq:
                        # Счётчик — после самого большого id. Отрицательные id (каналы Telegram) счётчик
                        # не двигают: он начинается с 1, а такие записи всегда создаются с явным id.
                        top = f'(SELECT MAX("{pk[0].name}") FROM "{table.name}")'
                        await d.execute(text(f"SELECT setval('{seq}', GREATEST(COALESCE({top}, 0), 1), "
                                             f"COALESCE({top}, 0) >= 1)"))

    bad = [(n, a, b) for n, a, b, lost in report if a - lost != b]
    for name, a, b, lost in report:
        if a or b:
            print(f"  {name:40} {a:>8} → {b:>8}" + (f"   пропущено {lost}" if lost else ""))
    if skipped:
        where = Path(config.DB_PATH).resolve().parent / "pg_import_skipped.jsonl"
        try:
            with open(where, "w", encoding="utf-8") as f:
                for x in skipped:
                    f.write(json.dumps(x, ensure_ascii=False, default=str) + "\n")
            print(f"Пропущено строк: {len(skipped)} — подробности в {where}")
        except OSError as e:
            print(f"Пропущено строк: {len(skipped)} (файл не записан: {e}):", skipped[:20])
    if cut:
        print("Подрезаны слишком длинные значения:", ", ".join(f"{k} ×{v}" for k, v in sorted(cut.items())))
    print(("Проверка без записи завершена." if dry_run else "Перенос завершён.")
          + f" Таблиц: {sum(1 for _, a, _, _ in report if a)}, строк: {sum(a for _, a, _, _ in report)}.")
    await src.dispose()
    await dst.dispose()
    if tmp:
        tmp.cleanup()
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
