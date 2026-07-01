"""Публикация в WordPress через REST API.

Бот создаёт запись (по умолчанию — ЧЕРНОВИК) на сайте. Авторизация — через
Application Password пользователя WordPress (Панель → Пользователи → Профиль →
«Пароли приложений»). Нужны переменные окружения:
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


async def create_post(
    title: str, html: str, status: str = "draft"
) -> tuple[dict | None, str]:
    """Создаёт запись в WordPress. Возвращает (данные_записи, ошибка).

    status: 'draft' (черновик) или 'publish' (сразу опубликовать).
    При успехе ошибка пустая, данные содержат id и ссылки (link, edit).
    """
    if not wp_enabled():
        return None, ("Публикация на сайт не настроена: задай WP_URL, WP_USER и "
                      "WP_APP_PASSWORD в переменных окружения.")
    url = f"{_wp_url()}/wp-json/wp/v2/posts"
    payload = {"title": title, "content": html, "status": status}
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
                # Понятные подсказки на частые ошибки
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
