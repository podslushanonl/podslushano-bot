"""Сайт видит изменения КонтактGuide сразу.

Сайт держит список специалистов в кэше (15 минут) и кэширует страницы целиком, поэтому
новая или изменённая карточка появлялась только после следующей публикации новости.
Раз в 2 минуты бот сравнивает «отпечаток» активных карточек с прошлым и, если что-то
поменялось (одобрение, правка, фото, снятие, конец срока), просит сайт обновиться.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging

from utils import wordpress as wp

log = logging.getLogger(__name__)

INTERVAL = 120


async def fingerprint() -> str:
    from utils.webserver import _active_specialists
    rows = await _active_specialists()
    h = hashlib.sha1()
    for s in sorted(rows, key=lambda x: x.id):
        h.update(repr((s.id, s.name, s.category, s.city, s.province, s.description, s.contact, bool(s.is_premium),
                       bool(s.is_online), s.photo_file_id, getattr(s, "card_color", None))).encode())
    return h.hexdigest()


async def site_sync_loop(bot=None) -> None:
    last = None
    while True:
        try:
            cur = await fingerprint()
            if last is not None and cur != last:
                ok = await wp.refresh_site("/guide/")
                log.info("КонтактGuide изменился: сайт %s", "обновлён" if ok else "не ответил")
            last = cur
        except Exception as e:  # noqa: BLE001
            log.info("Синхронизация КонтактGuide с сайтом: %s", e)
        await asyncio.sleep(INTERVAL)
