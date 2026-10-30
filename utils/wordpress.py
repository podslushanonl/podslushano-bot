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
import html as _html
import json
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
# Фоновые прогревы кэша: держим ссылки, чтобы задачи не собрал сборщик мусора
_WARM_TASKS: set[asyncio.Task] = set()


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


async def _warm(urls: list[str]) -> None:
    """Открывает страницы как браузер, чтобы Cache Enabler сохранил их заранее.

    После публикации плагин очищает кэш главной и ленты; первый посетитель ждал
    сборку страницы. Кэшируются только запросы с Accept: text/html.
    """
    await asyncio.sleep(3)
    headers = {"User-Agent": _UA, "Accept": "text/html"}
    try:
        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    async with session.get(url, headers=headers, ssl=_ssl_param(),
                                           timeout=aiohttp.ClientTimeout(total=60)) as resp:
                        await resp.read()
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    log.info("Прогрев кэша %s: %s", url, e)
    except Exception as e:  # noqa: BLE001
        log.info("Прогрев кэша не удался: %s", e)


async def refresh_site(page: str = "/events/") -> bool:
    """Просит сайт забыть ленту афиши из бота и очистить кэш страниц, затем прогревает афишу.

    Нужна после того, как админ добавил или убрал событие: иначе сайт показывал бы
    старую афишу до 10 минут, а закэшированные страницы — до следующей публикации.
    """
    if not wp_enabled():
        return False
    ok = False
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{_wp_url()}/wp-json/pn/v1/refresh", headers=_base_headers(),
                                    ssl=_ssl_param(), timeout=aiohttp.ClientTimeout(total=30)) as resp:
                ok = resp.status == 200
                if not ok:
                    log.info("Сайт не обновил афишу: HTTP %s", resp.status)
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        log.info("Сайт не обновил афишу: %s", e)
    warm_cache(f"{_wp_url()}{page}")
    return ok


def warm_cache(link: str = "") -> None:
    """Запускает в фоне прогрев новой записи, главной и ленты новостей."""
    base = _wp_url()
    if not base:
        return
    urls = list(dict.fromkeys(u for u in (link, f"{base}/", f"{base}/news/") if u))
    try:
        task = asyncio.get_running_loop().create_task(_warm(urls))
    except RuntimeError:
        return
    _WARM_TASKS.add(task)
    task.add_done_callback(_WARM_TASKS.discard)


def _auth_header() -> str:
    # Application Password может содержать пробелы — WordPress их игнорирует.
    token = f"{config.WP_USER}:{config.WP_APP_PASSWORD.replace(' ', '')}"
    return "Basic " + base64.b64encode(token.encode()).decode()


def edit_link(post_id: int) -> str:
    """Ссылка на редактирование записи в админке WordPress."""
    return f"{_wp_url()}/wp-admin/post.php?post={post_id}&action=edit"


def drafts_link() -> str:
    """Ссылка на список черновиков в админке (запасной вариант, если нет id)."""
    return f"{_wp_url()}/wp-admin/edit.php?post_status=draft&post_type=post"


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
    filename: str, data: bytes, mime: str = "image/jpeg",
    caption: str | None = None, alt_text: str | None = None,
) -> tuple[dict | None, str]:
    """Загружает картинку в медиатеку WordPress. Возвращает ({id, source_url}, ошибка).

    caption/alt_text — подпись и альтернативный текст (например «Фото: NOS»);
    ставятся вторым запросом, ошибка там не мешает самой загрузке.
    """
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
                        media = {"id": j.get("id"),
                                 "source_url": j.get("source_url", "")}
                        if media["id"] and (caption or alt_text):
                            await _update_media_meta(media["id"], caption, alt_text)
                        return media, ""
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


async def _wp_json(
    method: str, path: str, *, params: dict | None = None, payload: dict | None = None
) -> tuple[int, object]:
    """Простой JSON-запрос к REST API. Возвращает (HTTP-статус, разобранный JSON).

    Статус 0 — сеть/таймаут после всех попыток.
    """
    url = f"{_wp_url()}/wp-json/wp/v2/{path.lstrip('/')}"
    headers = {**_base_headers(), "Content-Type": "application/json"}
    for attempt in range(_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method, url, params=params, json=payload, headers=headers,
                    ssl=_ssl_param(), timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    body = await resp.text()
                    try:
                        data = json.loads(body)
                    except Exception:  # noqa: BLE001
                        data = None
                    if resp.status >= 400:
                        log.warning("WP %s %s: %s %s", method, path, resp.status, body[:300])
                    return resp.status, data
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("WP %s %s попытка %s: %s", method, path, attempt + 1, e)
            if attempt < _RETRIES - 1:
                await asyncio.sleep(2 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            log.warning("Ошибка WP %s %s: %s", method, path, e)
            return 0, None
    return 0, None


async def _update_media_meta(
    media_id: int, caption: str | None, alt_text: str | None
) -> None:
    payload: dict = {}
    if caption:
        payload["caption"] = caption
    if alt_text:
        payload["alt_text"] = alt_text
    status, _ = await _wp_json("POST", f"media/{media_id}", payload=payload)
    if status not in (200, 201):
        log.warning("Не удалось подписать фото %s (HTTP %s)", media_id, status)


async def ensure_category(name: str, parent_id: int | None = None) -> int | None:
    """id рубрики по названию; если такой нет — создаёт (дочерней к parent_id).

    Ищем по точному названию среди результатов поиска WordPress — так же, как
    импортёр темы (term_exists по имени). None — если не удалось.
    """
    name = (name or "").strip()
    if not name or not wp_enabled():
        return None
    status, data = await _wp_json(
        "GET", "categories",
        params={"search": name, "per_page": "100", "_fields": "id,name,parent"},
    )
    if status == 200 and isinstance(data, list):
        wanted = name.casefold()
        for cat in data:
            if _html.unescape(str(cat.get("name", ""))).strip().casefold() == wanted:
                return int(cat["id"])
    payload: dict = {"name": name}
    if parent_id:
        payload["parent"] = parent_id
    status, data = await _wp_json("POST", "categories", payload=payload)
    if status in (200, 201) and isinstance(data, dict) and data.get("id"):
        return int(data["id"])
    # Рубрика уже есть (поиск её не нашёл) — WordPress сообщает её id
    if isinstance(data, dict) and data.get("code") == "term_exists":
        term_id = (data.get("data") or {}).get("term_id") or data.get("additional_data")
        if isinstance(term_id, list):
            term_id = term_id[0] if term_id else None
        try:
            return int(term_id) if term_id else None
        except (TypeError, ValueError):
            return None
    return None


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
    excerpt: str | None = None,
    slug: str | None = None,
) -> tuple[dict | None, str]:
    """Создаёт запись в WordPress. Возвращает (данные_записи, ошибка).

    status: 'draft' (черновик) или 'publish'. category_ids — рубрики,
    featured_media — id картинки-обложки, excerpt — анонс, slug — адрес
    записи (пусто = WordPress сделает сам).
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
    if excerpt:
        payload["excerpt"] = excerpt
    if slug:
        payload["slug"] = slug
    headers = {**_base_headers(), "Content-Type": "application/json"}
    for attempt in range(_RETRIES):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, headers=headers, ssl=_ssl_param(),
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    body = await resp.text()
                    if resp.status in (200, 201):
                        try:
                            data = json.loads(body)
                        except Exception:  # noqa: BLE001
                            data = {}
                        pid = data.get("id") if isinstance(data, dict) else None
                        if not pid:
                            # Ответ без id — это отказ (защита хостинга и т.п.), а не запись
                            msg = (data.get("message", "")
                                   if isinstance(data, dict) else "")
                            log.warning("create_post: ответ без id (HTTP %s): %s",
                                        resp.status, body[:400])
                            low = (msg or body).lower()
                            if "imunify" in low or "bot-protection" in low:
                                return None, (
                                    "Хостинг-защита Imunify360 блокирует бота. "
                                    "Добавь IP бота в белый список Imunify360 "
                                    "(cPanel → Imunify360, или попроси хостинг).")
                            if msg:
                                return None, f"Сайт отклонил создание: {msg}"
                            return None, ("Сайт не вернул ID записи (запрос отклонён). "
                                          "Проверь защиту хостинга/плагины.")
                        link = data.get("link", "") if isinstance(data, dict) else ""
                        if data.get("status", status) == "publish":
                            warm_cache(link)
                        return {
                            "id": pid,
                            "link": link,
                            "edit": edit_link(pid),
                            "status": data.get("status", status),
                        }, ""
                    if resp.status in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("Location", "?")
                        return None, (
                            f"Сайт перенаправляет запрос (HTTP {resp.status}) на:\n{loc}\n"
                            "Из-за редиректа запись не создаётся. Поставь в Railway "
                            "WP_URL ровно как в адресе выше (обычно без www) и повтори.")
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

    # 4) Тестовое создание черновика — показываем СЫРОЙ ответ (статус, редирект,
    #    Content-Type, разобранный id / тело). Так видно настоящую причину «нет id».
    if wp_enabled():
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    f"{_wp_url()}/wp-json/wp/v2/posts",
                    json={"title": "WPTEST — можно удалить", "status": "draft",
                          "content": "Проверка связи бота."},
                    headers={**_base_headers(), "Content-Type": "application/json"},
                    ssl=_ssl_param(), allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as r:
                    ct = r.headers.get("Content-Type", "")
                    lines.append(f"\n🧪 Тест-создание: HTTP {r.status}, {ct}")
                    loc = r.headers.get("Location")
                    if r.status in (301, 302, 303, 307, 308) and loc:
                        lines.append(f"↪️ Редирект на: {loc}")
                        lines.append("👉 Поставь WP_URL ровно как в этом адресе "
                                     "(обычно без www).")
                    else:
                        raw = await r.text()
                        try:
                            d = json.loads(raw)
                            pid = d.get("id") if isinstance(d, dict) else None
                            if pid:
                                lines.append(f"✅ Запись создалась, id={pid} "
                                             "(удали тестовый черновик).")
                            else:
                                keys = (", ".join(list(d.keys())[:6])
                                        if isinstance(d, dict) else type(d).__name__)
                                lines.append(f"⚠️ В ответе нет id. Поля: {keys}")
                                lines.append(f"Тело: {raw[:250]}")
                        except Exception:  # noqa: BLE001
                            lines.append(f"⚠️ Ответ не JSON. Тело: {raw[:250]}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"Тест-создание — ошибка: {type(e).__name__}: {e}")
    return "\n".join(lines)


async def update_post(
    post_id: int, content: str | None = None, featured_media: int | None = None,
    title: str | None = None, excerpt: str | None = None,
) -> tuple[dict | None, str]:
    """Обновляет запись (тело/обложку/заголовок/анонс). Возвращает (данные, ошибка)."""
    if not wp_enabled():
        return None, "Публикация на сайт не настроена."
    if not isinstance(post_id, int) or post_id <= 0:
        return None, "Нет ID записи для обновления."
    url = f"{_wp_url()}/wp-json/wp/v2/posts/{post_id}"
    payload: dict = {}
    if content is not None:
        payload["content"] = content
    if featured_media:
        payload["featured_media"] = featured_media
    if title:
        payload["title"] = title
    if excerpt:
        payload["excerpt"] = excerpt
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
                        try:
                            data = json.loads(await resp.text())
                        except Exception:  # noqa: BLE001
                            data = {}
                        if isinstance(data, dict) and data.get("status") == "publish":
                            warm_cache(data.get("link", ""))
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
