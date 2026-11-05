"""Служебные страницы сайта из репозитория: wordpress/pages/<slug>.html → страница WordPress /<slug>/.

Сервер сам создаёт страницу, если её нет, и обновляет текст, если файл в репозитории изменился,
так что загружать такие страницы вручную через админку не нужно. Заголовок берётся из первой строки
файла — комментария вида <!-- Страница «Заголовок», адрес /slug/. … -->.
Нужен доступ к WordPress (WP_USER и WP_APP_PASSWORD), он уже используется для публикации новостей.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re

from utils import wordpress as wp

log = logging.getLogger(__name__)
PAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "wordpress", "pages")
_NORM = re.compile(r"\s+")


def read_pages(folder: str = PAGES_DIR) -> list[dict]:
    """Страницы из папки: slug (имя файла), title (из комментария), content (без комментария)."""
    out = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not name.endswith(".html"):
            continue
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            raw = f.read()
        m = re.match(r"\s*<!--(.*?)-->", raw, re.S)
        head = m.group(1) if m else ""
        t = re.search(r"«([^»]+)»", head)
        out.append({"slug": name[:-5], "title": t.group(1) if t else name[:-5],
                    "content": raw[m.end():].strip() if m else raw.strip()})
    return out


def same(a: str, b: str) -> bool:
    return _NORM.sub(" ", a or "").strip() == _NORM.sub(" ", b or "").strip()


async def sync_pages() -> list[str]:
    """Создаёт или обновляет страницы. Возвращает, что сделано: ['privacy-app: создана', …]."""
    if not wp.wp_enabled():
        return []
    done = []
    for p in read_pages():
        status, found = await wp._wp_json("GET", "pages", params={
            "slug": p["slug"], "status": "publish,draft,private", "context": "edit", "_fields": "id,content,title,status"})
        if status != 200 or not isinstance(found, list):
            log.warning("site_pages: cannot read page %s (%s)", p["slug"], status)
            continue
        payload = {"title": p["title"], "content": p["content"], "status": "publish", "slug": p["slug"]}
        if not found:
            st, _ = await wp._wp_json("POST", "pages", payload=payload)
            done.append(f"{p['slug']}: {'создана' if st in (200, 201) else f'ошибка {st}'}")
            continue
        page = found[0]
        raw = ((page.get("content") or {}).get("raw")) or ""
        if same(raw, p["content"]) and page.get("status") == "publish":
            continue
        st, _ = await wp._wp_json("POST", f"pages/{page['id']}", payload=payload)
        done.append(f"{p['slug']}: {'обновлена' if st == 200 else f'ошибка {st}'}")
    if done:
        log.info("site_pages: %s", "; ".join(done))
    return done


async def site_pages_loop() -> None:
    """Через минуту после старта и затем раз в сутки: страницы на сайте совпадают с репозиторием."""
    await asyncio.sleep(60)
    while True:
        try:
            await sync_pages()
        except Exception:  # noqa: BLE001
            log.exception("site_pages: sync failed")
        await asyncio.sleep(24 * 3600)
