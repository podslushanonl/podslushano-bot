"""Маленький веб-сервер рядом с ботом — принимает webhook оплаты от Mollie.

Mollie после оплаты дёргает POST /mollie-webhook с полем id=<payment_id>.
Мы проверяем платёж и публикуем/продлеваем размещение. Также есть health-check
на GET / (нужен Railway).
"""
import html as html_lib
import logging
from datetime import datetime

from aiohttp import web
from sqlalchemy import or_, select

import config
from database.db import get_session
from database.models import Specialist
from handlers.selfadd import on_payment_paid
from utils.contact_links import parse_contact_links
from utils.reviews import rating_badge, ratings_for, specialist_key
from utils.payments import get_payment

log = logging.getLogger(__name__)


async def _health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#eef2f8;
  margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center}}
 .card{{background:#fff;max-width:440px;margin:20px;padding:32px 28px;border-radius:18px;
  box-shadow:0 12px 34px rgba(0,0,0,.08);text-align:center}}
 img.logo{{max-width:180px;height:auto;margin-bottom:14px}}
 .ico{{font-size:54px;line-height:1}}
 h1{{font-size:22px;margin:12px 0 6px;color:#111}}
 p{{color:#555;line-height:1.55;margin:6px 0}}
 a.btn{{display:inline-block;margin-top:22px;background:#2aabee;color:#fff;text-decoration:none;
  padding:13px 24px;border-radius:12px;font-weight:600}}
</style></head>
<body><div class="card">
 {logo}
 <div class="ico">{ico}</div>
 <h1>{title}</h1>
 {body}
 <a class="btn" href="{bot}">Вернуться в Telegram</a>
</div></body></html>"""


def _render(title: str, ico: str, body_html: str) -> str:
    logo = f'<img class="logo" src="{config.LOGO_URL}" alt="logo">' if config.LOGO_URL else ""
    return _PAGE.format(title=title, ico=ico, body=body_html, logo=logo, bot=config.BOT_URL)


_DOC_PAGE = """<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#eef2f8;margin:0;padding:24px}}
 .wrap{{max-width:720px;margin:0 auto;background:#fff;padding:28px 30px;border-radius:16px;
  box-shadow:0 8px 24px rgba(0,0,0,.06)}}
 img.logo{{max-width:150px;margin-bottom:10px}}
 h1{{font-size:24px;margin:8px 0 4px}} h2{{font-size:18px;margin:22px 0 6px}}
 p,li{{color:#333;line-height:1.6}} .upd{{color:#888;font-size:13px;margin-bottom:10px}} a{{color:#2aabee}}
 .lang{{font-size:14px;margin:0 0 6px}}
</style></head><body><div class="wrap">{logo}{switch}{body}{company}</div></body></html>"""


def _company_block(lang: str) -> str:
    label = "Bedrijfsgegevens" if lang == "nl" else "Реквизиты"
    return (
        f"<h2>{label}</h2><p>{config.COMPANY_NAME}<br>{config.COMPANY_ADDRESS}<br>"
        f"KVK: {config.COMPANY_KVK} &middot; BTW: {config.COMPANY_BTW}<br>"
        f'<a href="mailto:{config.COMPANY_EMAIL}">{config.COMPANY_EMAIL}</a></p>'
    )


def _switch(page: str, lang: str) -> str:
    ru = "<b>Русский</b>" if lang == "ru" else f'<a href="/{page}?lang=ru">Русский</a>'
    nl = "<b>Nederlands</b>" if lang == "nl" else f'<a href="/{page}?lang=nl">Nederlands</a>'
    return f'<p class="lang">{ru} &nbsp;|&nbsp; {nl}</p>'

_PRIVACY_RU = """
<h1>Политика конфиденциальности</h1>
<p class="upd">Обновлено: 12.06.2026</p>
<p>Этот документ объясняет, как Telegram-бот сообщества «Подслушано в
Нидерландах» (@podslushano_nl_bot) обрабатывает ваши данные.</p>
<h2>Какие данные мы собираем</h2>
<ul>
 <li>имя/имя пользователя и ваш Telegram-ID;</li>
 <li>содержимое, которое вы отправляете (истории, вопросы, видео, заявки на
  рекламу и размещение) и ваши контактные данные;</li>
 <li>для платных размещений — данные специалиста/бизнеса и статус оплаты.
  Платежи проходят через Mollie; данные банковских карт мы не храним.</li>
</ul>
<h2>Зачем</h2>
<ul>
 <li>показ специалистов в гайде;</li>
 <li>модерация и связь с вами;</li>
 <li>обработка оплаты за размещение.</li>
</ul>
<h2>Основание обработки</h2>
<p>Ваше согласие и исполнение договора (GDPR/AVG).</p>
<h2>Передача третьим лицам</h2>
<p>Только по необходимости: Mollie (платежи), Telegram (мессенджер) и наш
хостинг (Railway, серверы в ЕС). Мы не продаём ваши данные.</p>
<h2>ИИ-ассистент</h2>
<p>Свободные вопросы могут обрабатываться сервисом ИИ (Anthropic) для
формирования ответа. Не отправляйте в чат чувствительные персональные данные.</p>
<p>Если вы добровольно присылаете фото письма/документа для разбора, оно
передаётся ИИ-сервису (Anthropic) только для формирования ответа и
<b>не сохраняется</b> нами. Не присылайте чужие документы без согласия их
владельца. Разбор носит справочный характер и не является юридической
консультацией.</p>
<h2>Хранение и ваши права</h2>
<p>Мы храним данные столько, сколько необходимо. Вы вправе запросить доступ,
исправление и удаление. Напишите боту или нам на почту — и мы удалим ваши данные.</p>
"""

_PRIVACY_NL = """
<h1>Privacyverklaring</h1>
<p class="upd">Laatst bijgewerkt: 12-06-2026</p>
<p>Deze verklaring legt uit hoe de Telegram-bot van Podslushano.nl
(@podslushano_nl_bot) met je gegevens omgaat.</p>
<h2>Welke gegevens we verwerken</h2>
<ul>
 <li>je naam/gebruikersnaam en Telegram-ID;</li>
 <li>inhoud die je instuurt (verhalen, vragen, video's, advertentie- en
  vermeldingsaanvragen) en je contactgegevens;</li>
 <li>bij betaalde vermeldingen: bedrijfs- en contactinformatie en de betaalstatus.
  Betalingen verlopen via Mollie; wij slaan geen kaartgegevens op.</li>
</ul>
<h2>Waarvoor</h2>
<ul>
 <li>het tonen van specialisten in de gids;</li>
 <li>moderatie en communicatie;</li>
 <li>het verwerken van betalingen voor vermeldingen.</li>
</ul>
<h2>Grondslag</h2>
<p>Toestemming en de uitvoering van de overeenkomst (AVG/GDPR).</p>
<h2>Delen met derden</h2>
<p>Alleen waar nodig: Mollie (betalingen), Telegram (berichtenplatform) en onze
hosting (Railway, servers in de EU). We verkopen je gegevens niet.</p>
<h2>AI-assistent</h2>
<p>Vrije vragen kunnen worden verwerkt door een AI-dienst (Anthropic) om te
antwoorden. Deel geen gevoelige persoonsgegevens in de chat.</p>
<h2>Bewaren en je rechten</h2>
<p>We bewaren gegevens zolang dat nodig is. Je hebt recht op inzage, correctie en
verwijdering. Stuur een bericht in de bot of mail ons.</p>
"""

_TERMS_RU = """
<h1>Условия размещения в гайде</h1>
<p class="upd">Обновлено: 12.06.2026</p>
<h2>Услуга</h2>
<p>Размещение вашей карточки (специалист или бизнес) в гайде «Подслушано в
Нидерландах» через Telegram-бот.</p>
<h2>Тарифы и срок</h2>
<p>Цена и период указаны в боте (месяц или год). Размещение действует выбранный
период и затем прекращается, если вы не продлите его новой оплатой. Перед
окончанием мы пришлём напоминание.</p>
<h2>Проверка</h2>
<p>Каждая заявка проверяется нами до публикации. Мы вправе отклонить или удалить
карточку — например, при неверном или неуместном содержании.</p>
<h2>Оплата</h2>
<p>Оплата проходит безопасно через Mollie (в т.ч. iDEAL).</p>
<h2>Право на отказ и возвраты</h2>
<p>У бизнес-клиентов нет законного «права на отказ». У потребителей есть 14 дней
на отказ; соглашаясь и запуская услугу сразу, вы даёте согласие на немедленное
исполнение. Если заявку отклонили — мы возвращаем сумму.</p>
<h2>Ответственность</h2>
<p>Рекламодатель отвечает за достоверность предоставленных данных. Гайд носит
информационный характер; мы не являемся стороной договорённостей между
пользователями и специалистами.</p>
<h2>Применимое право</h2>
<p>К настоящим условиям применяется право Нидерландов.</p>
"""

_TERMS_NL = """
<h1>Algemene voorwaarden — vermelding in de gids</h1>
<p class="upd">Laatst bijgewerkt: 12-06-2026</p>
<h2>Dienst</h2>
<p>Plaatsing van jouw vermelding (specialist of bedrijf) in de Podslushano-gids
via de Telegram-bot.</p>
<h2>Tarieven en looptijd</h2>
<p>De prijs en periode worden in de bot getoond (maandelijks of jaarlijks). De
vermelding is geldig voor de gekozen periode en verloopt daarna, tenzij je
verlengt via een nieuwe betaling. Vóór het einde sturen we een herinnering.</p>
<h2>Beoordeling</h2>
<p>Elke aanvraag wordt vóór publicatie door ons gecontroleerd. We kunnen een
vermelding weigeren of verwijderen, bijvoorbeeld bij onjuiste of ongepaste inhoud.</p>
<h2>Betaling</h2>
<p>Betalingen verlopen veilig via Mollie (o.a. iDEAL).</p>
<h2>Herroeping en restitutie</h2>
<p>Zakelijke klanten hebben geen wettelijk herroepingsrecht. Consumenten hebben in
beginsel 14 dagen herroepingsrecht; door akkoord te gaan en de dienst direct te
laten ingaan, stem je in met onmiddellijke uitvoering. Wordt je aanvraag
afgewezen, dan betalen we het bedrag terug.</p>
<h2>Verantwoordelijkheid</h2>
<p>De adverteerder is verantwoordelijk voor de juistheid van de aangeleverde
gegevens. De gids is informatief; wij zijn geen partij bij afspraken tussen
gebruikers en specialisten.</p>
<h2>Toepasselijk recht</h2>
<p>Op deze voorwaarden is Nederlands recht van toepassing.</p>
"""


def _doc(title: str, lang: str, switch: str, body: str) -> str:
    logo = f'<img class="logo" src="{config.LOGO_URL}" alt="logo">' if config.LOGO_URL else ""
    return _DOC_PAGE.format(
        lang=lang, title=title, logo=logo, switch=switch, body=body,
        company=_company_block(lang),
    )


def _lang(request: web.Request) -> str:
    return "nl" if request.query.get("lang") == "nl" else "ru"


async def _privacy(request: web.Request) -> web.Response:
    lang = _lang(request)
    title = "Privacyverklaring" if lang == "nl" else "Политика конфиденциальности"
    body = _PRIVACY_NL if lang == "nl" else _PRIVACY_RU
    return web.Response(
        text=_doc(title, lang, _switch("privacy", lang), body), content_type="text/html"
    )


async def _terms(request: web.Request) -> web.Response:
    lang = _lang(request)
    title = "Algemene voorwaarden" if lang == "nl" else "Условия размещения"
    body = _TERMS_NL if lang == "nl" else _TERMS_RU
    return web.Response(
        text=_doc(title, lang, _switch("terms", lang), body), content_type="text/html"
    )


async def _thanks(request: web.Request) -> web.Response:
    """Страница после оплаты: показывает реальный статус платежа."""
    title, ico, body = (
        "Спасибо!",
        "🙌",
        "<p>Мы обрабатываем ваш платёж. Статус придёт вам в Telegram.</p>",
    )
    sid = request.query.get("sid")
    if sid and sid.isdigit():
        try:
            async with get_session() as session:
                sp = await session.get(Specialist, int(sid))
            payment = await get_payment(sp.payment_id) if sp and sp.payment_id else None
            status = (payment or {}).get("status")
            if status == "paid":
                title, ico = "Оплата прошла успешно!", "✅"
                body = (
                    "<p>Спасибо! Ваша анкета отправлена на проверку.</p>"
                    "<p>Как только мы её одобрим, карточка появится в гайде — "
                    "бот напишет вам в Telegram.</p>"
                )
            elif status in ("failed", "canceled", "expired"):
                title, ico = "Оплата не завершена", "⚠️"
                body = (
                    "<p>Похоже, оплата не прошла. Ничего страшного — "
                    "можно попробовать ещё раз прямо в боте.</p>"
                )
        except Exception as e:  # noqa: BLE001 — страница не должна падать
            log.warning("Ошибка на странице оплаты: %s", e)
    return web.Response(text=_render(title, ico, body), content_type="text/html")


async def _active_specialists() -> list[Specialist]:
    """Все активные (видимые) специалисты, без дублей одного человека."""
    now = datetime.utcnow()
    async with get_session() as session:
        rows = (
            await session.scalars(
                select(Specialist)
                .where(
                    Specialist.status == "active",
                    or_(Specialist.paid_until.is_(None), Specialist.paid_until > now),
                )
                .order_by(Specialist.category, Specialist.name)
            )
        ).all()
    seen: set[tuple[str, str]] = set()
    uniq: list[Specialist] = []
    for s in rows:
        key = (s.name.strip().lower(), (s.contact or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    return uniq


async def _api_specialists(request: web.Request) -> web.Response:
    """JSON со всеми активными специалистами (для сайта). CORS открыт."""
    rows = await _active_specialists()
    ratings = await ratings_for([specialist_key(s.name, s.contact) for s in rows])
    data = []
    for s in rows:
        r = ratings.get(specialist_key(s.name, s.contact))
        data.append({
            "name": s.name,
            "category": s.category,
            "city": s.city or "",
            "province": s.province or "",
            "online": bool(s.is_online),
            "premium": bool(s.is_premium),
            "description": s.description or "",
            "contact": s.contact or "",
            "links": parse_contact_links(s.contact),
            "photo": _photo_url(s),
            "rating": r[0] if r else None,
            "reviews": r[1] if r else 0,
        })
    resp = web.json_response({"count": len(data), "specialists": data})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


_GUIDE_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Гайд специалистов — Подслушано в Нидерландах</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#eef2f8;margin:0;padding:20px;color:#222}}
 .wrap{{max-width:760px;margin:0 auto}}
 .top{{text-align:center;margin-bottom:14px}} .top img{{max-width:160px}}
 h1{{font-size:22px;margin:6px 0}} h2{{font-size:17px;margin:24px 0 8px;color:#2a6}}
 input{{width:100%;box-sizing:border-box;padding:12px 14px;border:1px solid #cfd6e4;border-radius:12px;font-size:15px;margin-bottom:8px}}
 .card{{background:#fff;border-radius:14px;padding:14px 16px;margin:8px 0;box-shadow:0 4px 14px rgba(0,0,0,.05)}}
 .ph{{width:100%;max-height:260px;object-fit:cover;border-radius:10px;margin-bottom:8px}}
 .nm{{font-weight:700}} .ds{{color:#555;margin:4px 0 8px;font-size:14px;line-height:1.45}}
 .lnks a{{display:inline-block;margin:4px 6px 0 0;padding:7px 12px;background:#2aabee;color:#fff;
  text-decoration:none;border-radius:10px;font-size:14px}}
 .muted{{color:#888;font-size:13px;text-align:center;margin-top:18px}}
</style></head><body><div class="wrap">
 <div class="top">{logo}<h1>Гайд специалистов 🇳🇱</h1></div>
 <input id="q" placeholder="Поиск: профессия, имя или город…" oninput="flt()">
 <div id="list">{body}</div>
 <p class="muted">Обновляется автоматически · podslushano.nl</p>
</div>
<script>
function flt(){{var v=document.getElementById('q').value.toLowerCase();
 document.querySelectorAll('#list .card').forEach(function(c){{
  c.style.display=c.innerText.toLowerCase().indexOf(v)>-1?'':'none';}});
 document.querySelectorAll('#list h2').forEach(function(h){{var n=h.nextElementSibling,s=false;
  while(n&&n.tagName!=='H2'){{if(n.classList.contains('card')&&n.style.display!=='none')s=true;n=n.nextElementSibling;}}
  h.style.display=s?'':'none';}});}}
</script>
</body></html>"""


def _guide_card(s: Specialist, badge: str = "") -> str:
    where = "онлайн" if s.is_online else (s.city or s.province or "")
    name = ("🌟 " if s.is_premium else "") + html_lib.escape(s.name)
    head = name + (f" · {html_lib.escape(where)}" if where else "")
    if badge:
        head += f' <span class="rt">{html_lib.escape(badge)}</span>'
    desc = (
        f'<div class="ds">{html_lib.escape(s.description)}</div>' if s.description else ""
    )
    links = parse_contact_links(s.contact)
    btns = "".join(
        f'<a href="{html_lib.escape(l["url"])}" target="_blank" rel="noopener">{l["label"]}</a>'
        for l in links
    )
    purl = _photo_url(s)
    photo = f'<img class="ph" src="{html_lib.escape(purl)}" alt="" loading="lazy">' if purl else ""
    return f'<div class="card">{photo}<div class="nm">{head}</div>{desc}<div class="lnks">{btns}</div></div>'


async def _guide(request: web.Request) -> web.Response:
    rows = await _active_specialists()
    ratings = await ratings_for([specialist_key(s.name, s.contact) for s in rows])
    groups: dict[str, list[Specialist]] = {}
    for s in rows:
        groups.setdefault(s.category, []).append(s)
    parts: list[str] = []
    for cat in sorted(groups):
        parts.append(f"<h2>{html_lib.escape(cat).capitalize()}</h2>")
        # премиум — вперёд внутри категории
        cat_specs = sorted(groups[cat], key=lambda s: 0 if s.is_premium else 1)
        parts.extend(
            _guide_card(s, rating_badge(ratings.get(specialist_key(s.name, s.contact))))
            for s in cat_specs
        )
    body = "".join(parts) or "<p>Пока пусто.</p>"
    logo = f'<img src="{config.LOGO_URL}" alt="logo"><br>' if config.LOGO_URL else ""
    return web.Response(
        text=_GUIDE_PAGE.format(logo=logo, body=body), content_type="text/html"
    )


async def _mollie_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.post()
        payment_id = data.get("id")
        bot = request.app["bot"]
        if payment_id:
            await on_payment_paid(bot, payment_id)
    except Exception as e:  # noqa: BLE001 — Mollie всегда ждёт 200, иначе ретраит
        log.warning("Ошибка обработки webhook Mollie: %s", e)
    return web.Response(text="ok")


def _photo_url(s: Specialist) -> str | None:
    """Абсолютный URL фото карточки (через наш прокси), или None."""
    if not getattr(s, "photo_file_id", None):
        return None
    return f"{config.WEBHOOK_BASE_URL or ''}/sp-photo/{s.id}"


async def _sp_photo(request: web.Request) -> web.Response:
    """Отдаёт фото карточки: тянем файл из Telegram по file_id и стримим как картинку."""
    sid_s = request.match_info.get("sid", "")
    if not sid_s.isdigit():
        return web.Response(status=404, text="not found")
    async with get_session() as session:
        sp = await session.get(Specialist, int(sid_s))
    if sp is None or not sp.photo_file_id:
        return web.Response(status=404, text="no photo")
    bot = request.app["bot"]
    try:
        f = await bot.get_file(sp.photo_file_id)
        buf = await bot.download_file(f.file_path)
        data = buf.read()
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось отдать фото #%s: %s", sid_s, e)
        return web.Response(status=404, text="no photo")
    resp = web.Response(body=data, content_type="image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


# Карта granular-категорий бота → 8 укрупнённых групп виджета каталога на сайте
_SITE_GROUP = {
    "нутрициолог": "Здоровье", "психолог": "Здоровье", "стоматолог": "Здоровье", "врач": "Здоровье",
    "массаж": "Бьюти", "парикмахер": "Бьюти", "косметолог": "Бьюти",
    "мастер маникюра": "Бьюти", "тату": "Бьюти", "стилист": "Бьюти",
    "риелтор": "Дом", "дизайнер": "Дом", "ремонт": "Дом", "мастер на час": "Дом", "клининг": "Дом",
    "репетитор": "Образование", "автошкола": "Образование", "музыка": "Образование",
    "кондитер": "Вкус", "еда": "Вкус",
    "няня": "Дети", "аниматор": "Дети",
    "ведущий": "Впечатления", "фотограф": "Впечатления", "гид": "Впечатления",
    "фитнес": "Впечатления", "творчество": "Впечатления",
    "юрист": "Услуги", "бухгалтер": "Услуги", "веб-разработчик": "Услуги",
    "автосервис": "Услуги", "услуги": "Услуги",
}


async def _api_guide(request: web.Request) -> web.Response:
    """JSON-фид для кастомного виджета каталога на сайте (KG_DATA_URL).

    Формат: массив [{name, desc, prov, cat}] — ровно то, что понимает виджет.
    Контакты идут в desc, виджет сам делает ссылки кликабельными.
    """
    rows = await _active_specialists()
    rows = sorted(rows, key=lambda s: (0 if s.is_premium else 1, s.category, s.name))
    data = []
    for s in rows:
        desc = " · ".join(p for p in [s.description, s.contact] if p)
        data.append({
            "name": s.name,
            "desc": desc,
            "prov": "" if s.is_online else (s.province or ""),
            "cat": _SITE_GROUP.get(s.category, "Услуги"),
            "premium": bool(s.is_premium),
            "photo": _photo_url(s) or "",
        })
    resp = web.json_response(data)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


async def start_webserver(bot) -> web.AppRunner:
    """Запускает веб-сервер на нужном порту (для webhook оплаты и health-check)."""
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", _health)
    app.router.add_get("/thanks", _thanks)
    app.router.add_get("/privacy", _privacy)
    app.router.add_get("/terms", _terms)
    app.router.add_get("/guide", _guide)
    app.router.add_get("/sp-photo/{sid}", _sp_photo)
    app.router.add_get("/api/specialists.json", _api_specialists)
    app.router.add_get("/api/guide.json", _api_guide)
    app.router.add_post("/mollie-webhook", _mollie_webhook)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    log.info("Веб-сервер запущен на порту %s", config.PORT)
    return runner
