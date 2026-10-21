"""Практические справки на сайт: «Как получить BSN», «Как найти huisarts» и т.п.

Цель — чтобы на запрос в Google («как получить BSN») находилась наша статья. Поэтому
справка длинная и полностью решает вопрос: что это, кому нужно, пошагово, документы,
сроки и цены, частые ошибки, вопросы и ответы, официальные ссылки.

Раз в SITE_GUIDES_INTERVAL секунд бот берёт следующую тему из TOPICS (когда список
закончится — просит Claude предложить новую), пишет справку по официальным сайтам
(веб-поиск только по госсайтам) и публикует её в рубрике «Справочник». Справки старше
SITE_GUIDES_REFRESH_DAYS дней переписываются заново — правила и суммы меняются каждый год.

Текст приходит от Claude структурированным JSON (абзацы, шаги, чек-листы, таблицы,
выноски «Совет»/«Важно», вопросы-ответы) и собирается в HTML с классами pg-*,
которые оформлены в теме сайта (wordpress/src/app.src.html).
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

import config
from database.db import get_session
from database.models import SiteGuide
from utils import wordpress as wp
from utils.ai import (_create_with_server_tool_continuation, _extract_text_and_sources, _get_client,
                      _parse_json, _web_search_tool, ai_enabled)
from utils.site_news import make_slug

log = logging.getLogger(__name__)

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
CATEGORY = "Справочник"
# Повторная попытка темы, на которой генерация не удалась
RETRY_FAILED = timedelta(days=1)

# Официальные источники для веб-поиска: только госсайты и профильные организации
SOURCES = [
    "rijksoverheid.nl", "government.nl", "overheid.nl", "mijnoverheid.nl", "belastingdienst.nl",
    "toeslagen.nl", "ind.nl", "digid.nl", "uwv.nl", "werk.nl", "svb.nl", "duo.nl", "kvk.nl",
    "business.gov.nl", "rvo.nl", "cbr.nl", "rdw.nl", "cjib.nl", "justis.nl", "politie.nl",
    "juridischloket.nl", "huurcommissie.nl", "thuisarts.nl", "zorgverzekeringslijn.nl",
    "zorginstituutnederland.nl", "rivm.nl", "ggd.nl", "nibud.nl", "inburgeren.nl", "cak.nl",
    "ns.nl", "ov-chipkaart.nl", "amsterdam.nl", "rotterdam.nl", "denhaag.nl", "utrecht.nl",
    "consuwijzer.nl", "acm.nl", "autoriteitpersoonsgegevens.nl", "netherlandsworldwide.nl",
]

# Темы: ключ (он же адрес записи в базе), запрос, как его пишут в Google
TOPICS: list[tuple[str, str]] = [
    ("bsn", "Как получить BSN в Нидерландах"),
    ("digid", "Как получить DigiD"),
    ("registratsiya-gemeente", "Как зарегистрироваться в gemeente (inschrijving BRP)"),
    ("bankovskiy-schet", "Как открыть банковский счёт в Нидерландах"),
    ("zorgverzekering", "Как выбрать и оформить медстраховку (zorgverzekering)"),
    ("huisarts", "Как найти и записаться к huisarts (семейному врачу)"),
    ("zorgtoeslag", "Как получить zorgtoeslag (пособие на медстраховку)"),
    ("huurtoeslag", "Как получить huurtoeslag (пособие на аренду)"),
    ("belastingaangifte", "Как подать налоговую декларацию (belastingaangifte)"),
    ("30-protsentov", "Налоговая льгота 30%-regeling: кому положена и как оформить"),
    ("arenda-zhilya", "Как снять жильё в Нидерландах и не попасться мошенникам"),
    ("huurcommissie", "Как снизить слишком высокую аренду через Huurcommissie"),
    ("voditelskie-prava", "Как обменять водительские права на нидерландские"),
    ("ov-chipkaart", "Как получить OV-chipkaart и платить в транспорте"),
    ("kinderbijslag", "Как получить kinderbijslag (детское пособие)"),
    ("kinderopvangtoeslag", "Как получить kinderopvangtoeslag (пособие на детский сад)"),
    ("shkola-rebenok", "Как записать ребёнка в школу в Нидерландах"),
    ("ww-posobie", "Как получить пособие по безработице WW"),
    ("zzp-kvk", "Как зарегистрироваться как ZZP в KvK"),
    ("btw-zzp", "BTW для ZZP: как платить и подавать декларацию"),
    ("inburgering", "Inburgering: как сдать экзамен на интеграцию"),
    ("naturalisatie", "Как получить гражданство Нидерландов (naturalisatie)"),
    ("tijdelijke-bescherming", "Временная защита для украинцев в Нидерландах: права и документы"),
    ("ziekmelding", "Как оформить больничный (ziekmelding) на работе"),
    ("energie", "Как выбрать и сменить поставщика электричества и газа"),
    ("cjib-shtraf", "Как оплатить или обжаловать штраф CJIB"),
    ("vog", "Как получить справку о несудимости VOG"),
    ("aangifte-politie", "Как подать заявление в полицию (aangifte)"),
    ("112-ekstrennaya-pomoshch", "Куда звонить в экстренной ситуации: 112, huisartsenpost, 0900-8844"),
    ("rozhdenie-rebenka", "Как зарегистрировать рождение ребёнка в Нидерландах"),
    ("studiefinanciering", "Как получить studiefinanciering (стипендию DUO)"),
    ("aow-pensiya", "Пенсия AOW: кому положена и сколько"),
    ("hypotheek", "Как купить жильё и получить ипотеку (hypotheek)"),
    ("parkeervergunning", "Как получить разрешение на парковку (parkeervergunning)"),
    ("kwijtschelding", "Как получить освобождение от муниципальных налогов (kwijtschelding)"),
    ("tandarts", "Как найти стоматолога и что покрывает страховка"),
    ("rabota-poisk", "Как найти работу в Нидерландах без знания нидерландского"),
    ("trudovoy-dogovor", "Трудовой договор в Нидерландах: что проверить перед подписанием"),
    ("vakantiegeld", "Vakantiegeld и отпуск: что положено работнику"),
    ("pereezd-adres", "Как сменить адрес при переезде внутри Нидерландов"),
    ("vyezd-iz-nl", "Как правильно выписаться при выезде из Нидерландов"),
    ("auto-registratsiya", "Как зарегистрировать машину из-за границы (RDW, BPM)"),
    ("mrb-nalog-avto", "Налог на машину (motorrijtuigenbelasting): сколько и как платить"),
    ("musor", "Как сортировать и выбрасывать мусор в Нидерландах"),
    ("yurist-besplatno", "Где получить бесплатную юридическую помощь (Juridisch Loket)"),
    ("toeslagen-vozvrat", "Что делать, если нужно вернуть toeslagen"),
    ("nibud-dolgi", "Что делать при долгах: помощь gemeente и schuldhulpverlening"),
    ("psiholog", "Как попасть к психологу (GGZ) по страховке"),
]

_SYSTEM = """Ты редактор podslushano.nl — медиа для русскоязычных жителей Нидерландов.
Пишешь практическую справку по теме, которую люди ищут в Google. Справка должна
ПОЛНОСТЬЮ решить вопрос читателя: после неё не нужно искать где-то ещё.

Факты бери только из официальных источников через веб-поиск (госсайты Нидерландов).
Суммы, сроки, ставки и правила — актуальные на текущий год. Если точной цифры не нашёл —
не выдумывай, напиши, где её проверить. Не давай устаревших данных.

Стиль: простой русский, на «вы», дружелюбно и по делу, без воды и канцелярита.
Нидерландские термины и названия пиши латиницей, при первом упоминании поясняй
по-русски: «gemeente (муниципалитет)». Города Нидерландов — латиницей (Amsterdam).
Не пиши «NL» — пиши «Нидерланды». Без эмодзи. Можно выделять важное **жирным**.
Абзацы короткие: 2–4 предложения. Чередуй текст со списками, шагами, таблицами
и выносками, чтобы читать было легко.

Объём: 1600–2600 слов. Структура: 6–9 разделов. Обязательно: раздел «пошагово»
с блоком steps, список нужных документов блоком check, сроки и стоимость (лучше
таблицей), частые ошибки и как их избежать, что делать, если что-то пошло не так.

Ответь ТОЛЬКО JSON без пояснений:
{"title": "заголовок под поисковый запрос, до 70 символов, с годом, если уместно",
 "lead": "описание для поиска, 140–160 символов: о чём и что читатель узнает",
 "summary": [["Где оформить", "В gemeente по месту жительства"], ["Срок", "..."], ...],
 "sections": [{"h": "заголовок раздела", "blocks": [БЛОК, ...]}, ...],
 "faq": [{"q": "вопрос как его задают в Google", "a": "ответ 2–4 предложения"}, ...],
 "sources": [{"t": "название страницы", "url": "https://официальный-сайт"}, ...]}

summary — 3–6 пар «что — коротко», главное одним взглядом.
faq — 5–8 вопросов. sources — 2–6 официальных ссылок, которые ты реально открыл.

БЛОК — один из:
["p", "абзац"]
["h3", "подзаголовок внутри раздела"]
["list", ["пункт", "пункт", ...]]
["check", ["документ или условие", ...]]          — чек-лист
["steps", [{"t": "короткое название шага", "d": "что сделать, 1–3 предложения"}, ...]]
["table", {"head": ["...", "..."], "rows": [["...", "..."], ...]}]
["tip", "полезный совет"]
["warn", "важное предупреждение или частая ошибка"]
["info", "дополнительная справка"]"""

_SUGGEST_SYSTEM = """Ты редактор podslushano.nl — медиа для русскоязычных жителей Нидерландов.
Предложи ОДНУ новую тему практической справки, которую русскоязычные жители Нидерландов
часто ищут в Google («как получить…», «как оформить…», «что делать, если…»):
документы, налоги, пособия, жильё, работа, здоровье, дети, транспорт, быт.
Тема не должна повторять уже написанные. Ответь ТОЛЬКО JSON:
{"key": "латинский-ключ-через-дефис", "query": "Как ... (запрос, как его пишут в Google)"}"""

_BLOCK_TYPES = {"p", "h3", "list", "check", "steps", "table", "tip", "warn", "info"}


def enabled() -> bool:
    return config.SITE_GUIDES_ENABLED and wp.wp_enabled() and ai_enabled()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _s(v: object, limit: int = 2000) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


# --- Проверка ответа Claude ---------------------------------------------------------

def _block(b: object) -> list | None:
    if not isinstance(b, (list, tuple)) or len(b) != 2 or b[0] not in _BLOCK_TYPES:
        return None
    kind, val = b
    if kind in ("p", "h3", "tip", "warn", "info"):
        return [kind, _s(val)] if _s(val) else None
    if kind in ("list", "check"):
        items = [_s(x, 600) for x in (val or []) if _s(x, 600)] if isinstance(val, list) else []
        return [kind, items[:15]] if items else None
    if kind == "steps":
        steps = [{"t": _s(x.get("t"), 160), "d": _s(x.get("d"), 900)}
                 for x in (val or []) if isinstance(x, dict) and _s(x.get("t"), 160)] if isinstance(val, list) else []
        return [kind, steps[:12]] if len(steps) >= 2 else None
    if kind == "table" and isinstance(val, dict):
        head = [_s(x, 120) for x in (val.get("head") or [])][:5]
        rows = [[_s(c, 400) for c in r][:len(head)] for r in (val.get("rows") or []) if isinstance(r, list)][:20]
        rows = [r + [""] * (len(head) - len(r)) for r in rows]
        return [kind, {"head": head, "rows": rows}] if len(head) >= 2 and rows else None
    return None


def _words(guide: dict) -> int:
    parts = [guide["lead"], *(v for pair in guide["summary"] for v in pair)]
    for sec in guide["sections"]:
        parts.append(sec["h"])
        for kind, val in sec["blocks"]:
            if isinstance(val, str):
                parts.append(val)
            elif kind == "steps":
                parts += [x["t"] + " " + x["d"] for x in val]
            elif kind == "table":
                parts += val["head"] + [c for r in val["rows"] for c in r]
            else:
                parts += val
    parts += [f["q"] + " " + f["a"] for f in guide["faq"]]
    return len(" ".join(parts).split())


def validate(data: object, min_words: int = 1200) -> dict | None:
    """Очищенная справка или None, если ответ неполный (короткий, без шагов, без FAQ)."""
    if not isinstance(data, dict):
        return None
    title, lead = _s(data.get("title"), 140), _s(data.get("lead"), 300)
    if not title or not lead:
        return None
    summary = [[_s(p[0], 60), _s(p[1], 200)] for p in (data.get("summary") or [])
               if isinstance(p, (list, tuple)) and len(p) == 2 and _s(p[0]) and _s(p[1])][:6]
    sections = []
    for sec in data.get("sections") or []:
        if not isinstance(sec, dict) or not _s(sec.get("h")):
            continue
        blocks = [x for x in (_block(b) for b in (sec.get("blocks") or [])) if x]
        if blocks:
            sections.append({"h": _s(sec["h"], 160), "blocks": blocks})
    faq = [{"q": _s(f.get("q"), 200), "a": _s(f.get("a"), 1200)} for f in (data.get("faq") or [])
           if isinstance(f, dict) and _s(f.get("q")) and _s(f.get("a"))][:10]
    sources = [{"t": _s(x.get("t"), 160) or _s(x.get("url"), 160), "url": _s(x.get("url"), 400)}
               for x in (data.get("sources") or [])
               if isinstance(x, dict) and re.match(r"^https://[^\s\"'<>]+$", _s(x.get("url"), 400))][:8]
    has_steps = any(b[0] == "steps" for s in sections for b in s["blocks"])
    if len(sections) < 5 or not has_steps or len(faq) < 4 or not sources:
        return None
    guide = {"title": title, "lead": lead, "summary": summary, "sections": sections, "faq": faq, "sources": sources}
    return guide if _words(guide) >= min_words else None


# --- HTML ------------------------------------------------------------------------------

def _inline(text: str) -> str:
    """Экранирует текст и превращает **жирный** в <strong>."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(text))


_MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
           "сентября", "октября", "ноября", "декабря")
_NOTE = {"tip": "Совет", "warn": "Важно", "info": "Полезно знать"}


def _render_block(kind: str, val) -> str:
    if kind == "p":
        return f"<p>{_inline(val)}</p>"
    if kind == "h3":
        return f"<h3>{_inline(val)}</h3>"
    if kind in ("list", "check"):
        cls = ' class="pg-check"' if kind == "check" else ' class="pg-list"'
        return f"<ul{cls}>" + "".join(f"<li>{_inline(x)}</li>" for x in val) + "</ul>"
    if kind == "steps":
        return '<ol class="pg-steps">' + "".join(
            f'<li><p class="pg-step-t">{_inline(x["t"])}</p>' + (f'<p>{_inline(x["d"])}</p>' if x["d"] else "") + "</li>"
            for x in val) + "</ol>"
    if kind == "table":
        head = "".join(f"<th>{_inline(h)}</th>" for h in val["head"])
        rows = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in val["rows"])
        return f'<div class="pg-table"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>'
    return (f'<div class="pg-note pg-{kind}"><p class="pg-note-h">{_NOTE[kind]}</p>'
            f"<p>{_inline(val)}</p></div>")


def build_html(guide: dict, when: datetime | None = None) -> str:
    """Тело записи: один блок «HTML» Gutenberg, чтобы WordPress не переделывал разметку."""
    when = (when or datetime.now(timezone.utc)).astimezone(AMSTERDAM)
    minutes = max(3, round(_words(guide) / 200))
    out = [f'<p class="pg-meta">Обновлено {when.day} {_MONTHS[when.month - 1]} {when.year} · '
           f"{minutes} мин чтения</p>"]
    if guide["summary"]:
        out.append('<div class="pg-sum"><p class="pg-sum-h">Коротко</p><dl>' + "".join(
            f"<div><dt>{_inline(k)}</dt><dd>{_inline(v)}</dd></div>" for k, v in guide["summary"]) + "</dl></div>")
    toc = [(f"pg-{i}", s["h"]) for i, s in enumerate(guide["sections"], 1)] + [("pg-faq", "Частые вопросы")]
    out.append('<nav class="pg-toc" aria-label="Содержание"><p class="pg-toc-h">Содержание</p><ol>' + "".join(
        f'<li><a href="#{a}">{_inline(t)}</a></li>' for a, t in toc) + "</ol></nav>")
    for i, sec in enumerate(guide["sections"], 1):
        out.append(f'<h2 id="pg-{i}">{_inline(sec["h"])}</h2>')
        out += [_render_block(k, v) for k, v in sec["blocks"]]
    out.append('<section class="pg-faq"><h2 id="pg-faq">Частые вопросы</h2>' + "".join(
        f'<details class="pg-faq-i"><summary>{_inline(f["q"])}</summary><div><p>{_inline(f["a"])}</p></div></details>'
        for f in guide["faq"]) + "</section>")
    out.append('<div class="pg-cta"><p class="pg-cta-t">Нужен специалист, который говорит по-русски?</p>'
               '<p>Юристы, бухгалтеры, врачи и консультанты в Нидерландах — в нашем КонтактGuide.</p>'
               '<p><a class="pg-cta-b" href="/guide/">Найти специалиста</a></p></div>')
    out.append('<div class="pg-src"><p class="pg-src-h">Официальные источники</p><ul>' + "".join(
        f'<li><a href="{html.escape(x["url"])}" target="_blank" rel="noopener">{html.escape(x["t"])}</a></li>'
        for x in guide["sources"]) + "</ul><p>Правила и суммы меняются. Справка обновляется, но перед важным "
        "решением сверьтесь с официальным сайтом.</p></div>")
    return "<!-- wp:html -->\n" + "\n".join(out) + "\n<!-- /wp:html -->"


# --- Claude ------------------------------------------------------------------------------

async def _ask(system: str, content: str, max_tokens: int, search: bool) -> str:
    kwargs = dict(model=config.SITE_GUIDES_MODEL, max_tokens=max_tokens, system=system,
                  messages=[{"role": "user", "content": content}],
                  extra_body={"output_config": {"effort": "medium" if search else "low"}})
    tools = _web_search_tool(SOURCES, max_uses=8) if search else None
    if tools:
        kwargs["tools"] = tools
    resp = await _create_with_server_tool_continuation(_get_client(), max_continuations=4, **kwargs)
    return _extract_text_and_sources(resp)[0].strip()


async def write_guide(query: str) -> dict | None:
    today = datetime.now(AMSTERDAM)
    content = (f"Тема справки: {query}\nСегодня {today.day} {_MONTHS[today.month - 1]} {today.year} года — "
               "данные нужны актуальные на эту дату.")
    for attempt in range(2):
        try:
            raw = await _ask(_SYSTEM, content, 20000, search=True)
        except Exception as e:  # noqa: BLE001
            log.warning("Справка «%s»: ошибка Claude: %s", query, e)
            return None
        guide = validate(_parse_json(raw))
        if guide:
            return guide
        log.warning("Справка «%s»: ответ не прошёл проверку (попытка %s)", query, attempt + 1)
    return None


async def suggest_topic(done: list[str]) -> tuple[str, str] | None:
    try:
        raw = await _ask(_SUGGEST_SYSTEM, "Уже написаны:\n" + "\n".join(f"- {t}" for t in done[-150:]), 400, search=False)
    except Exception as e:  # noqa: BLE001
        log.warning("Справки: не удалось предложить тему: %s", e)
        return None
    data = _parse_json(raw)
    key = make_slug(_s(data.get("key"), 80).replace("-", " ")) if isinstance(data, dict) else ""
    query = _s(data.get("query"), 300) if isinstance(data, dict) else ""
    return (key[:80], query) if key and query else None


# --- Очередь и публикация -----------------------------------------------------------------

_category_id: int | None = None


async def _category() -> int | None:
    global _category_id
    if _category_id is None:
        _category_id = await wp.ensure_category(CATEGORY)
    return _category_id


async def next_job(now: datetime | None = None) -> tuple[str, str, SiteGuide | None] | None:
    """(ключ, запрос, существующая справка для обновления | None) или None, если делать нечего."""
    now = now or _now()
    async with get_session() as session:
        rows = {g.key: g for g in (await session.scalars(select(SiteGuide))).all()}
    def retry(g: SiteGuide) -> bool:
        return g.status == "failed" and not g.wp_post_id and g.tried_at < now - RETRY_FAILED

    for key, query in TOPICS:
        g = rows.get(key)
        if g is None or retry(g):
            return key, query, g
    # Неудачные темы, предложенные Claude (их нет в TOPICS)
    for g in sorted(rows.values(), key=lambda x: x.tried_at):
        if retry(g):
            return g.key, g.query, g
    stale = [g for g in rows.values() if g.wp_post_id
             and g.updated_at < now - timedelta(days=config.SITE_GUIDES_REFRESH_DAYS)
             and g.tried_at < now - RETRY_FAILED]
    if stale:
        g = min(stale, key=lambda x: x.updated_at)
        return g.key, g.query, g
    # Список тем закончился — новая тема от Claude (не чаще раза в интервал, как и всё остальное)
    picked = await suggest_topic([g.query for g in rows.values()] + [q for _, q in TOPICS])
    if picked and picked[0] not in rows and picked[0] not in dict(TOPICS):
        return picked[0], picked[1], None
    return None


async def _save(key: str, query: str, status: str, *, title: str = "", post: dict | None = None,
                reason: str | None = None) -> None:
    async with get_session() as session:
        g = (await session.scalars(select(SiteGuide).where(SiteGuide.key == key))).first()
        if g is None:
            g = SiteGuide(key=key, query=query, status=status)
            session.add(g)
        g.query, g.reason, g.tried_at = query, reason, _now()
        if title:
            g.title = title
        if post:
            # Срок свежести сдвигаем только после удачной записи: неудачное обновление повторится через сутки
            g.status, g.updated_at = "published", g.tried_at
            g.wp_post_id = post.get("id") or g.wp_post_id
            g.wp_link = post.get("link") or g.wp_link
        elif not g.wp_post_id:
            g.status = status
        await session.commit()


async def _notify_admins(bot, text: str) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось уведомить админа %s: %s", admin_id, e)


async def publish(bot, key: str, query: str, existing: SiteGuide | None) -> bool:
    guide = await write_guide(query)
    if not guide:
        await _save(key, query, "failed", reason="Claude не дал полную справку")
        return False
    body = build_html(guide)
    if existing and existing.wp_post_id:
        post, err = await wp.update_post(existing.wp_post_id, content=body, title=guide["title"], excerpt=guide["lead"])
        if post:
            post["link"] = existing.wp_link
        action = "обновлена"
    else:
        cat = await _category()
        post, err = await wp.create_post(guide["title"], body, status="publish",
                                         category_ids=[cat] if cat else None, excerpt=guide["lead"],
                                         slug=make_slug(guide["title"]) or None)
        action = "опубликована"
    if not post:
        await _save(key, query, "failed", reason=f"WordPress: {err}"[:300])
        return False
    await _save(key, query, "published", title=guide["title"], post=post)
    log.info("Справка %s: %s → %s", action, key, post.get("link"))
    if bot is not None:
        await _notify_admins(bot, f"Справка {action} на сайте\n<b>{html.escape(guide['title'])}</b>\n"
                                  f"{html.escape(post.get('link') or wp.edit_link(post['id']))}")
    return True


async def _recently_worked(now: datetime) -> bool:
    """Была ли попытка за последний интервал: перезапуски сервера не должны публиковать справки чаще."""
    async with get_session() as session:
        last = (await session.scalars(select(SiteGuide.tried_at).order_by(SiteGuide.tried_at.desc()).limit(1))).first()
    return bool(last and last > now - timedelta(seconds=config.SITE_GUIDES_INTERVAL))


async def run_once(bot, now: datetime | None = None) -> None:
    now = now or _now()
    if await _recently_worked(now):
        return
    job = await next_job(now)
    if job:
        await publish(bot, *job)


async def site_guides_loop(bot) -> None:
    """Фоновая задача: одна справка (новая или обновлённая) раз в SITE_GUIDES_INTERVAL секунд."""
    if not enabled():
        log.info("Справки сайта выключены (нужны WP_*, ключ ИИ и SITE_GUIDES_ENABLED≠0)")
        return
    await asyncio.sleep(120)
    while True:
        try:
            await run_once(bot)
        except Exception as e:  # noqa: BLE001
            log.exception("Справки сайта: ошибка запуска: %s", e)
        # Проверяем чаще интервала: сам интервал отсчитывается от последней попытки в базе
        await asyncio.sleep(min(1800, config.SITE_GUIDES_INTERVAL))
