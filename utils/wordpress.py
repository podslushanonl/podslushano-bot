"""Публикация в WordPress через REST API.

Бот создаёт запись (по умолчанию — ЧЕРНОВИК) на сайте: с категорией, обложкой
и, если фото несколько, аккуратной галереей. Авторизация — через Application
Password пользователя WordPress (Профиль → «Пароли приложений»). Переменные:
  WP_URL           — адрес сайта (по умолчанию берётся SITE_URL)
  WP_USER          — логин пользователя WordPress
  WP_APP_PASSWORD  — пароль приложения (можно с пробелами, как выдаёт WP)
"""
from __future__ import annotations

import base64
import logging

import aiohttp

import config

log = logging.getLogger(__name__)


def wp_enabled() -> bool:
    """Настроена ли публикация на сайт (есть адрес, логин и пароль приложения)."""
    return bool(_wp_url() and config.WP_USER and config.WP_APP_PASSWORD)


def _wp_url() -> str:
    return (config.WP_URL or config.SITE_URL or "").rstrip("/")


def _auth_header() -> str:
    # Application Password может содержать пробелы — WordPress их игнорирует.
    token = f"{config.WP_USER}:{config.WP_APP_PASSWORD.replace(' ', '')}"
    return "Basic " + base64.b64encode(token.encode()).decode()


def edit_link(post_id: int) -> str:
    """Ссылка на редактирование записи в админке WordPress."""
    return f"{_wp_url()}/wp-admin/post.php?post={post_id}&action=edit"


async def list_categories() -> list[dict]:
    """Список рубрик сайта: [{id, name}]. Пустой список — если не удалось."""
    if not wp_enabled():
        return []
    url = f"{_wp_url()}/wp-json/wp/v2/categories?per_page=100&_fields=id,name"
    headers = {"Authorization": _auth_header()}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return [{"id": c["id"], "name": c.get("name", "")} for c in data]
    except Exception as e:  # noqa: BLE001
        log.warning("Ошибка list_categories: %s", e)
        return []


async def upload_media(
    filename: str, data: bytes, mime: str = "image/jpeg"
) -> tuple[dict | None, str]:
    """Загружает картинку в медиатеку WordPress. Возвращает ({id, source_url}, ошибка)."""
    if not wp_enabled():
        return None, "Публикация на сайт не настроена."
    url = f"{_wp_url()}/wp-json/wp/v2/media"
    headers = {
        "Authorization": _auth_header(),
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": mime,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, data=data, headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status in (200, 201):
                    j = await resp.json()
                    return {"id": j.get("id"), "source_url": j.get("source_url", "")}, ""
                body = await resp.text()
                log.warning("WP upload_media %s: %s", resp.status, body[:300])
                if resp.status in (401, 403):
                    return None, "WordPress отклонил загрузку фото (права/пароль)."
                return None, f"Не удалось загрузить фото (ошибка {resp.status})."
    except Exception as e:  # noqa: BLE001
        log.warning("Ошибка upload_media: %s", e)
        return None, "Не удалось загрузить фото (сеть/таймаут)."


def gallery_block(images: list[dict]) -> str:
    """HTML-галерея WordPress из загруженных фото — аккуратной сеткой, не кучей.

    images — список {id, source_url}. 1 фото — одиночный блок, 2+ — сетка колонками.
    """
    if not images:
        return ""
    inner = "".join(
        f'<!-- wp:image {{"id":{im["id"]},"sizeSlug":"large"}} -->'
        f'<figure class="wp-block-image size-large">'
        f'<img src="{im["source_url"]}" class="wp-image-{im["id"]}"/></figure>'
        f"<!-- /wp:image -->"
        for im in images if im.get("id")
    )
    if not inner:
        return ""
    cols = 1 if len(images) == 1 else (2 if len(images) <= 4 else 3)
    return (
        f'<!-- wp:gallery {{"columns":{cols},"linkTo":"none"}} -->'
        f'<figure class="wp-block-gallery has-nested-images columns-{cols} is-cropped">'
        f"{inner}</figure><!-- /wp:gallery -->"
    )


async def create_post(
    title: str,
    html: str,
    status: str = "draft",
    category_ids: list[int] | None = None,
    featured_media: int | None = None,
) -> tuple[dict | None, str]:
    """Создаёт запись в WordPress. Возвращает (данные_записи, ошибка).

    status: 'draft' (черновик) или 'publish'. category_ids — рубрики,
    featured_media — id картинки-обложки.
    """
    if not wp_enabled():
        return None, ("Публикация на сайт не настроена: задай WP_URL, WP_USER и "
                      "WP_APP_PASSWORD в переменных окружения.")
    url = f"{_wp_url()}/wp-json/wp/v2/posts"
    payload: dict = {"title": title, "content": html, "status": status}
    if category_ids:
        payload["categories"] = category_ids
    if featured_media:
        payload["featured_media"] = featured_media
    headers = {"Authorization": _auth_header(), "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                body = await resp.text()
                if resp.status in (200, 201):
                    data = await resp.json()
                    return {
                        "id": data.get("id"),
                        "link": data.get("link", ""),
                        "edit": edit_link(data.get("id")),
                        "status": data.get("status", status),
                    }, ""
                if resp.status in (401, 403):
                    return None, ("WordPress отклонил доступ (нет прав или неверный "
                                  "пароль приложения). Проверь WP_USER и WP_APP_PASSWORD.")
                if resp.status == 404:
                    return None, ("REST API не найден (404). Проверь WP_URL и что "
                                  "включены «постоянные ссылки» в WordPress.")
                log.warning("WP create_post %s: %s", resp.status, body[:300])
                return None, f"WordPress вернул ошибку {resp.status}."
    except Exception as e:  # noqa: BLE001
        log.warning("Ошибка публикации в WordPress: %s", e)
        return None, "Не удалось связаться с сайтом (сеть/таймаут)."
