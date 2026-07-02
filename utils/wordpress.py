"""Публикация в WordPress через REST API.

Бот создаёт запись (по умолчанию — ЧЕРНОВИК) на сайте: с категорией, обложкой
и, если фото несколько, аккуратной галереей. Авторизация — через Application
Password пользователя WordPress (Профиль → «Пароли приложений»). Переменные:
  WP_URL           — адрес сайта (по умолчанию берётся SITE_URL)
  WP_USER          — логин пользователя WordPress
  WP_APP_PASSWORD  — пароль приложения (можно с пробелами, как выдаёт WP)
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
from collections import defaultdict

import aiohttp

import config

log = logging.getLogger(__name__)

# Браузерный User-Agent: без него защитные плагины (Wordfence) часто блокируют
# запросы, приняв бота за подозрительный трафик.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# Сколько раз повторять запрос при таймауте/сетевой ошибке (Wordfence может
# кратковременно троттлить при серии запросов — пауза помогает восстановиться).
_RETRIES = 3


def _base_headers() -> dict:
    return {
        "Authorization": _auth_header(),
        "User-Agent": _UA,
        "Accept": "application/json",
    }


def _ssl_param():
    """aiohttp ssl-параметр: False = не проверять сертификат (для самоподписанных)."""
    return None if config.WP_VERIFY_SSL else False


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
    for attempt in range(_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=_base_headers(), ssl=_ssl_param(),
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    return [{"id": c["id"], "name": c.get("name", "")} for c in data]
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("list_categories попытка %s: %s", attempt + 1, e)
            if attempt < _RETRIES - 1:
                await asyncio.sleep(2 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            log.warning("Ошибка list_categories: %s", e)
            return []
    return []


async def upload_media(
    filename: str, data: bytes, mime: str = "image/jpeg"
) -> tuple[dict | None, str]:
    """Загружает картинку в медиатеку WordPress. Возвращает ({id, source_url}, ошибка)."""
    if not wp_enabled():
        return None, "Публикация на сайт не настроена."
    url = f"{_wp_url()}/wp-json/wp/v2/media"
    headers = {
        **_base_headers(),
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": mime,
    }
    for attempt in range(_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, data=data, headers=headers, ssl=_ssl_param(),
                    timeout=aiohttp.ClientTimeout(total=90),
                ) as resp:
                    if resp.status in (200, 201):
                        j = await resp.json()
                        return {"id": j.get("id"),
                                "source_url": j.get("source_url", "")}, ""
                    body = await resp.text()
                    log.warning("WP upload_media %s: %s", resp.status, body[:300])
                    if resp.status in (401, 403):
                        return None, "WordPress отклонил загрузку фото (права/пароль)."
                    if resp.status == 429:
                        return None, "Сайт временно ограничил частоту запросов (429)."
                    return None, f"Не удалось загрузить фото (ошибка {resp.status})."
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("upload_media попытка %s: %s", attempt + 1, e)
            if attempt < _RETRIES - 1:
                await asyncio.sleep(2 * (attempt + 1))
            else:
                return None, "Не удалось загрузить фото (сеть/таймаут)."
        except Exception as e:  # noqa: BLE001
            log.warning("Ошибка upload_media: %s", e)
            return None, "Не удалось загрузить фото (сеть/таймаут)."
    return None, "Не удалось загрузить фото (сеть/таймаут)."


def section_titles(body_html: str) -> list[str]:
    """Заголовки разделов статьи (<h2>) — по ним раскладываем фото по пунктам."""
    raw = re.findall(r"<h2[^>]*>(.*?)</h2>", body_html or "", re.S | re.I)
    return [re.sub(r"<[^>]+>", "", t).strip() for t in raw]


def image_block(im: dict) -> str:
    """Одиночная картинка блоком WordPress."""
    if not im.get("id"):
        return ""
    return (
        f'<!-- wp:image {{"id":{im["id"]},"sizeSlug":"large"}} -->'
        f'<figure class="wp-block-image size-large">'
        f'<img src="{im["source_url"]}" class="wp-image-{im["id"]}"/></figure>'
        f"<!-- /wp:image -->"
    )


def build_content_with_images(
    body_html: str, placements: list[dict]
) -> tuple[str, int | None]:
    """Расставляет фото по статье согласно выбору пользователя.

    placements — список {'im': {id, source_url}, 'where': 'top'|'end'|<int раздел>}.
    'top' — обложка (featured, в тело не вставляется). <int> — после N-го <h2>.
    'end' — в конец. Возвращает (готовый_html, id_обложки|None).
    """
    section_imgs: dict[int, list[str]] = defaultdict(list)
    end_imgs: list[str] = []
    top_extra: list[str] = []
    featured: int | None = None
    for p in placements:
        im, where = p.get("im") or {}, p.get("where")
        fig = image_block(im)
        if not fig:
            continue
        if where == "top":
            if featured is None:
                featured = im.get("id")
            else:
                top_extra.append(fig)  # вторая «обложка» → в начало тела
        elif where == "end":
            end_imgs.append(fig)
        else:
            try:
                section_imgs[int(where)].append(fig)
            except (TypeError, ValueError):
                end_imgs.append(fig)
    # Вставляем фото сразу после нужного </h2>
    out = ""
    h2i = -1
    for tok in re.split(r"(</h2>)", body_html or ""):
        out += tok
        if tok == "</h2>":
            h2i += 1
            out += "".join(section_imgs.get(h2i, []))
    return "".join(top_extra) + out + "".join(end_imgs), featured


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
    headers = {**_base_headers(), "Content-Type": "application/json"}
    for attempt in range(_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, headers=headers, ssl=_ssl_param(),
                    timeout=aiohttp.ClientTimeout(total=60),
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
                    if resp.status == 429:
                        return None, ("Сайт временно ограничил частоту запросов (429) — "
                                      "вероятно Wordfence. Попробуй меньше фото за раз "
                                      "или ослабь rate-limit в Wordfence.")
                    log.warning("WP create_post %s: %s", resp.status, body[:300])
                    return None, f"WordPress вернул ошибку {resp.status}."
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("create_post попытка %s: %s", attempt + 1, e)
            if attempt < _RETRIES - 1:
                await asyncio.sleep(2 * (attempt + 1))
            else:
                return None, "Не удалось связаться с сайтом (сеть/таймаут)."
        except Exception as e:  # noqa: BLE001
            log.warning("Ошибка публикации в WordPress: %s", e)
            return None, "Не удалось связаться с сайтом (сеть/таймаут)."
    return None, "Не удалось связаться с сайтом (сеть/таймаут)."


async def diagnose() -> str:
    """Проверка связи бота с сайтом: внешний IP бота + ответ REST API.

    Помогает понять, блокирует ли сайт/Wordfence бота (403/таймаут) и какой
    IP нужно добавить в белый список Wordfence.
    """
    lines: list[str] = []
    # 1) Внешний IP бота — его добавляют в белый список Wordfence
    ip = "не определён"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.ipify.org",
                             timeout=aiohttp.ClientTimeout(total=15)) as r:
                ip = (await r.text()).strip()
    except Exception as e:  # noqa: BLE001
        ip = f"не удалось ({type(e).__name__})"
    lines.append(f"🌐 Внешний IP бота: <code>{ip}</code>")

    if not _wp_url():
        lines.append("⚠️ WP_URL не задан.")
        return "\n".join(lines)
    lines.append(f"Сайт: {_wp_url()}")
    lines.append(f"Проверка SSL: {'вкл' if config.WP_VERIFY_SSL else 'выкл'}")

    # 2) Доступен ли REST API (с текущими настройками SSL)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{_wp_url()}/wp-json/",
                             headers={"User-Agent": _UA, "Accept": "application/json"},
                             ssl=_ssl_param(),
                             timeout=aiohttp.ClientTimeout(total=25)) as r:
                if r.status == 200:
                    lines.append("✅ REST API отвечает (HTTP 200).")
                elif r.status == 403:
                    lines.append("⛔ HTTP 403 — сайт блокирует бота. Добавь IP выше "
                                 "в белый список Wordfence.")
                else:
                    body = (await r.text())[:250].replace("\n", " ").strip()
                    server = r.headers.get("Server", "")
                    powered = r.headers.get("X-Powered-By", "")
                    lines.append(f"HTTP {r.status} от /wp-json/.")
                    if server or powered:
                        lines.append(f"Сервер: {server} {powered}".strip())
                    if body:
                        lines.append(f"Ответ: {body}")
    except aiohttp.ClientConnectorCertificateError:
        lines.append("🔒 Сертификат сайта не проходит проверку (самоподписанный).")
        # Пробуем без проверки сертификата — если ок, подсказываем решение
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{_wp_url()}/wp-json/", headers={"User-Agent": _UA},
                                 ssl=False,
                                 timeout=aiohttp.ClientTimeout(total=25)) as r:
                    if r.status in (200, 401, 403):
                        lines.append("👉 Без проверки сертификата сайт отвечает. "
                                     "Реши: поставь в Railway <code>WP_VERIFY_SSL=0</code> "
                                     "— публикация заработает.")
                    else:
                        lines.append(f"Без проверки: HTTP {r.status}.")
        except Exception as e:  # noqa: BLE001
            lines.append(f"И без проверки не вышло: {type(e).__name__}.")
        return "\n".join(lines)
    except asyncio.TimeoutError:
        lines.append("⏱ Таймаут на /wp-json/ — сайт не отвечает боту (вероятно, IP "
                     "заблокирован/отбрасывается фаерволом). Добавь IP выше в белый "
                     "список Wordfence.")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        lines.append(f"Ошибка связи: {type(e).__name__}: {e}")
        return "\n".join(lines)

    # 3) Проверка авторизации (пароль приложения)
    if wp_enabled():
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{_wp_url()}/wp-json/wp/v2/users/me",
                                 headers=_base_headers(), ssl=_ssl_param(),
                                 timeout=aiohttp.ClientTimeout(total=25)) as r:
                    if r.status == 200:
                        lines.append("✅ Авторизация работает (пароль приложения OK).")
                    elif r.status in (401, 403):
                        lines.append("⛔ Авторизация отклонена — проверь WP_USER и "
                                     "WP_APP_PASSWORD.")
                    else:
                        body = (await r.text())[:200].replace("\n", " ").strip()
                        lines.append(f"Авторизация: HTTP {r.status}. {body}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"Авторизация — ошибка: {type(e).__name__}.")
    else:
        lines.append("⚠️ WP_USER/WP_APP_PASSWORD не заданы.")
    return "\n".join(lines)


async def update_post(
    post_id: int, content: str | None = None, featured_media: int | None = None
) -> tuple[dict | None, str]:
    """Обновляет запись (тело/обложку). Возвращает (данные, ошибка)."""
    if not wp_enabled():
        return None, "Публикация на сайт не настроена."
    url = f"{_wp_url()}/wp-json/wp/v2/posts/{post_id}"
    payload: dict = {}
    if content is not None:
        payload["content"] = content
    if featured_media:
        payload["featured_media"] = featured_media
    if not payload:
        return {"id": post_id}, ""
    headers = {**_base_headers(), "Content-Type": "application/json"}
    for attempt in range(_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, headers=headers, ssl=_ssl_param(),
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status in (200, 201):
                        return {"id": post_id}, ""
                    body = await resp.text()
                    log.warning("WP update_post %s: %s", resp.status, body[:300])
                    return None, f"WordPress вернул ошибку {resp.status}."
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("update_post попытка %s: %s", attempt + 1, e)
            if attempt < _RETRIES - 1:
                await asyncio.sleep(2 * (attempt + 1))
            else:
                return None, "Не удалось связаться с сайтом (сеть/таймаут)."
        except Exception as e:  # noqa: BLE001
            log.warning("Ошибка update_post: %s", e)
            return None, "Не удалось связаться с сайтом (сеть/таймаут)."
    return None, "Не удалось связаться с сайтом (сеть/таймаут)."
