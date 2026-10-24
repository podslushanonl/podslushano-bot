"""Учёт расходов на Claude API: токены и примерная стоимость каждого запроса бота по дням.

Каждый ответ messages.create клиента из utils.ai проходит через record(): в лог пишется
строка с токенами и ценой, а в таблицу meta (ключ ai_cost:ГГГГ-ММ-ДД) — сумма за день по
моделям. Админ видит итог командой /ai_cost. Цены — прайс Anthropic за 1 млн токенов, поиск
в интернете — $10 за 1000 запросов. Это оценка: точная сумма — в консоли Anthropic.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

AMS = ZoneInfo("Europe/Amsterdam")
# модель (начало id) → ($ за 1 млн входных, $ за 1 млн выходных)
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0), "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0), "claude-opus-5": (5.0, 25.0), "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0), "claude-opus-4": (5.0, 25.0),
}
SEARCH_USD = 0.01


def _price(model: str) -> tuple[float, float]:
    for prefix in sorted(PRICES, key=len, reverse=True):
        if (model or "").startswith(prefix):
            return PRICES[prefix]
    return PRICES["claude-sonnet-4-6"]   # неизвестная модель: считаем по дорогой, чтобы не занизить


def cost(model: str, usage) -> tuple[dict, float]:
    """Токены ответа и примерная цена в долларах."""
    g = (lambda k: int(getattr(usage, k, 0) or 0)) if usage is not None else (lambda k: 0)
    stu = getattr(usage, "server_tool_use", None) if usage is not None else None
    t = {"in": g("input_tokens"), "out": g("output_tokens"), "cache_w": g("cache_creation_input_tokens"),
         "cache_r": g("cache_read_input_tokens"), "search": int(getattr(stu, "web_search_requests", 0) or 0)}
    pin, pout = _price(model)
    usd = (t["in"] * pin + t["cache_w"] * pin * 1.25 + t["cache_r"] * pin * 0.1 + t["out"] * pout) / 1e6
    return t, usd + t["search"] * SEARCH_USD


async def record(model: str, response) -> None:
    try:
        t, usd = cost(model, getattr(response, "usage", None))
        log.info("Claude: %s in=%s out=%s поиск=%s ≈$%.4f", model, t["in"] + t["cache_w"] + t["cache_r"], t["out"],
                 t["search"], usd)
        from database.db import get_session
        from database.models import Meta
        key = "ai_cost:" + datetime.now(AMS).date().isoformat()
        async with get_session() as session:
            row = await session.get(Meta, key)
            try:
                day = json.loads(row.value) if row else {}
            except ValueError:
                day = {}
            m = day.setdefault(model or "?", {"calls": 0, "in": 0, "out": 0, "search": 0, "usd": 0.0})
            m["calls"] += 1
            m["in"] += t["in"] + t["cache_w"] + t["cache_r"]
            m["out"] += t["out"]
            m["search"] += t["search"]
            m["usd"] = round(m["usd"] + usd, 4)
            value = json.dumps(day)
            if row:
                row.value = value
            else:
                session.add(Meta(key=key, value=value))
            await session.commit()
    except Exception as e:  # noqa: BLE001 — учёт не должен ломать ответ
        log.info("Учёт расходов Claude не записан: %s", e)


def instrument(client):
    """Оборачивает client.messages.create, чтобы каждый ответ попадал в учёт."""
    if getattr(client, "_pn_usage", False):
        return client
    orig = client.messages.create

    async def create(*args, **kwargs):
        resp = await orig(*args, **kwargs)
        await record(kwargs.get("model", ""), resp)
        return resp

    client.messages.create = create
    client._pn_usage = True
    return client


async def days(n: int = 7) -> list[tuple[str, dict]]:
    """Последние n дней учёта: [(дата, {модель: итоги})], новые сверху."""
    from sqlalchemy import select

    from database.db import get_session
    from database.models import Meta
    async with get_session() as session:
        rows = (await session.scalars(select(Meta).where(Meta.key.like("ai_cost:%")))).all()
    out = []
    for r in rows:
        try:
            out.append((r.key.split(":", 1)[1], json.loads(r.value)))
        except ValueError:
            continue
    return sorted(out, reverse=True)[:n]
