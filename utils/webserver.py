"""Маленький веб-сервер рядом с ботом — принимает webhook оплаты от Mollie.

Mollie после оплаты дёргает POST /mollie-webhook с полем id=<payment_id>.
Мы проверяем платёж и публикуем/продлеваем размещение. Также есть health-check
на GET / (нужен Railway).
"""
import html as html_lib
import logging
import re
from datetime import datetime

from aiohttp import web
from sqlalchemy import or_, select

import config
from database.db import get_session
from database.models import AdLead, Specialist
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
<p class="upd">Обновлено: 23.06.2026</p>
<p>Эта политика объясняет, как сервис «Подслушано в Нидерландах»
(Telegram-бот @podslushano_nl_bot) обрабатывает персональные данные.
Ответственный за обработку (verwerkingsverantwoordelijke) — компания,
указанная в реквизитах внизу страницы.</p>

<h2>Какие данные мы обрабатываем</h2>
<ul>
 <li>данные Telegram: ваш ID, имя и имя пользователя;</li>
 <li>содержимое, которое вы присылаете: истории, вопросы, видео, заявки на
  рекламу и размещение, а также указанные вами контакты;</li>
 <li>объявления на доске: заголовок, описание, фото, цена, город, контакт;</li>
 <li>карточки специалистов/бизнеса: данные специалиста, контакты, e-mail для
  счёта и статус оплаты;</li>
 <li>отзывы и оценки, которые вы оставляете;</li>
 <li>данные об оплате: статус и идентификатор платежа. Платежи проходят через
  Mollie; данные банковских карт мы не получаем и не храним;</li>
 <li>технические и аналитические события (например, факт поиска или заявки).</li>
</ul>

<h2>Цели и правовые основания (GDPR/AVG)</h2>
<ul>
 <li>показ специалистов, объявлений и афиши — исполнение договора (ст. 6(1)(b));</li>
 <li>модерация, безопасность и связь с вами — законный интерес (ст. 6(1)(f));</li>
 <li>обработка оплаты и выставление счёта — исполнение договора и юридическая
  обязанность по налоговому учёту (ст. 6(1)(b), 6(1)(c));</li>
 <li>ответы ИИ-ассистента — законный интерес/ваше согласие (ст. 6(1)(a),(f));</li>
 <li>анонсы и рассылки — ваше согласие, его можно отозвать в любой момент;</li>
 <li>аналитика для улучшения сервиса — законный интерес.</li>
</ul>

<h2>Кому мы передаём данные (процессоры)</h2>
<p>Только тем, кто нужен для работы сервиса, по договорам обработки:</p>
<ul>
 <li>Telegram — мессенджер, через который работает бот;</li>
 <li>Mollie — обработка платежей;</li>
 <li>Anthropic — ИИ-ассистент (обработка ваших вопросов для ответа);</li>
 <li>Resend и/или Google (Gmail) — отправка счетов на e-mail;</li>
 <li>Railway — хостинг (серверы в ЕС);</li>
 <li>Google (Places) — фотографии мест для постов; ваши персональные данные
  при этом не передаются.</li>
</ul>
<p>Мы не продаём ваши данные и не используем их для рекламы третьих лиц.</p>

<h2>Передача за пределы ЕЭЗ</h2>
<p>Часть сервисов (например, Anthropic) находится в США. Передача защищена
стандартными договорными условиями ЕС (SCC) и дополнительными мерами.</p>

<h2>Сроки хранения</h2>
<ul>
 <li>заявки и переписка для модерации — до 12 месяцев;</li>
 <li>активные карточки и объявления — пока они размещены, затем разумный срок;</li>
 <li>счета и данные о платежах — 7 лет (налоговое требование Нидерландов);</li>
 <li>отзывы — пока актуальны или до вашего запроса об удалении;</li>
 <li>аналитика — в обезличенном виде.</li>
</ul>

<h2>Ваши права</h2>
<p>Вы вправе: получить доступ к своим данным, исправить их, удалить, ограничить
обработку, на переносимость, возразить против обработки и отозвать согласие.
Чтобы воспользоваться — напишите боту или нам на почту (реквизиты внизу).</p>
<p>Вы также можете подать жалобу в надзорный орган — Autoriteit Persoonsgegevens
(<a href="https://autoriteitpersoonsgegevens.nl">autoriteitpersoonsgegevens.nl</a>).</p>

<h2>Автоматические решения</h2>
<p>Мы не принимаем юридически значимых решений автоматически и не занимаемся
профилированием.</p>

<h2>Дети</h2>
<p>Сервис не предназначен для лиц младше 16 лет. Если вам меньше 16, пользуйтесь
сервисом только с согласия родителя или опекуна.</p>

<h2>ИИ-ассистент</h2>
<p>Свободные вопросы и присланные фото документов обрабатываются ИИ-сервисом
(Anthropic) только для формирования ответа и <b>не сохраняются</b> нами. Не
присылайте чувствительные или чужие персональные данные без согласия. Ответы
носят справочный характер и не являются юридической консультацией.</p>

<h2>Cookies и безопасность</h2>
<p>На наших страницах нет рекламных или трекинговых cookies. Мы принимаем
разумные технические и организационные меры для защиты данных.</p>

<h2>Изменения</h2>
<p>Мы можем обновлять эту политику; актуальная дата указана сверху.</p>
"""

_PRIVACY_NL = """
<h1>Privacyverklaring</h1>
<p class="upd">Laatst bijgewerkt: 23-06-2026</p>
<p>Deze verklaring legt uit hoe de dienst «Podslushano in Nederland»
(Telegram-bot @podslushano_nl_bot) persoonsgegevens verwerkt. De
verwerkingsverantwoordelijke is het bedrijf vermeld in de bedrijfsgegevens
onderaan deze pagina.</p>

<h2>Welke gegevens we verwerken</h2>
<ul>
 <li>Telegram-gegevens: je ID, naam en gebruikersnaam;</li>
 <li>inhoud die je instuurt: verhalen, vragen, video's, advertentie- en
  vermeldingsaanvragen en de door jou opgegeven contactgegevens;</li>
 <li>advertenties op het prikbord: titel, omschrijving, foto, prijs, plaats, contact;</li>
 <li>vermeldingen van specialisten/bedrijven: gegevens, contact, factuur-e-mail
  en betaalstatus;</li>
 <li>beoordelingen en waarderingen die je achterlaat;</li>
 <li>betaalgegevens: status en betaal-ID. Betalingen lopen via Mollie; wij
  ontvangen of bewaren geen kaartgegevens;</li>
 <li>technische en analytische gebeurtenissen (zoals een zoekopdracht of aanvraag).</li>
</ul>

<h2>Doelen en grondslagen (AVG/GDPR)</h2>
<ul>
 <li>tonen van specialisten, advertenties en agenda — uitvoering overeenkomst (art. 6(1)(b));</li>
 <li>moderatie, veiligheid en communicatie — gerechtvaardigd belang (art. 6(1)(f));</li>
 <li>betalingen en facturen — uitvoering overeenkomst en wettelijke (fiscale)
  verplichting (art. 6(1)(b), 6(1)(c));</li>
 <li>antwoorden van de AI-assistent — gerechtvaardigd belang/toestemming (art. 6(1)(a),(f));</li>
 <li>aankondigingen en mailings — je toestemming, die je altijd kunt intrekken;</li>
 <li>analyse ter verbetering van de dienst — gerechtvaardigd belang.</li>
</ul>

<h2>Met wie we gegevens delen (verwerkers)</h2>
<p>Alleen waar nodig voor de dienst, op basis van verwerkersovereenkomsten:</p>
<ul>
 <li>Telegram — het berichtenplatform van de bot;</li>
 <li>Mollie — betalingsverwerking;</li>
 <li>Anthropic — AI-assistent (verwerkt je vragen om te antwoorden);</li>
 <li>Resend en/of Google (Gmail) — verzenden van facturen per e-mail;</li>
 <li>Railway — hosting (servers in de EU);</li>
 <li>Google (Places) — foto's van locaties voor posts; je persoonsgegevens
  worden hierbij niet gedeeld.</li>
</ul>
<p>We verkopen je gegevens niet en gebruiken ze niet voor advertenties van derden.</p>

<h2>Doorgifte buiten de EER</h2>
<p>Sommige diensten (zoals Anthropic) bevinden zich in de VS. Doorgifte is
beschermd met EU-modelcontractbepalingen (SCC) en aanvullende maatregelen.</p>

<h2>Bewaartermijnen</h2>
<ul>
 <li>aanvragen en correspondentie voor moderatie — tot 12 maanden;</li>
 <li>actieve vermeldingen en advertenties — zolang ze geplaatst zijn, daarna een
  redelijke termijn;</li>
 <li>facturen en betaalgegevens — 7 jaar (Nederlandse fiscale bewaarplicht);</li>
 <li>beoordelingen — zolang relevant of tot je verzoek om verwijdering;</li>
 <li>analyse — in geanonimiseerde vorm.</li>
</ul>

<h2>Je rechten</h2>
<p>Je hebt recht op inzage, correctie, verwijdering, beperking van de verwerking,
dataportabiliteit, bezwaar en het intrekken van toestemming. Stuur hiervoor een
bericht in de bot of mail ons (gegevens onderaan).</p>
<p>Je kunt ook een klacht indienen bij de Autoriteit Persoonsgegevens
(<a href="https://autoriteitpersoonsgegevens.nl">autoriteitpersoonsgegevens.nl</a>).</p>

<h2>Geautomatiseerde besluiten</h2>
<p>We nemen geen besluiten met rechtsgevolg op puur geautomatiseerde wijze en doen
niet aan profilering.</p>

<h2>Kinderen</h2>
<p>De dienst is niet bedoeld voor personen jonger dan 16 jaar. Ben je jonger dan
16, gebruik de dienst dan alleen met toestemming van een ouder of voogd.</p>

<h2>AI-assistent</h2>
<p>Vrije vragen en ingestuurde foto's van documenten worden door een AI-dienst
(Anthropic) uitsluitend verwerkt om te antwoorden en worden door ons <b>niet
bewaard</b>. Deel geen gevoelige of andermans persoonsgegevens zonder toestemming.
Antwoorden zijn informatief en vormen geen juridisch advies.</p>

<h2>Cookies en beveiliging</h2>
<p>Onze pagina's gebruiken geen reclame- of trackingcookies. We nemen redelijke
technische en organisatorische maatregelen om gegevens te beschermen.</p>

<h2>Wijzigingen</h2>
<p>We kunnen deze verklaring bijwerken; de actuele datum staat bovenaan.</p>
"""

_TERMS_RU = """
<h1>Условия использования</h1>
<p class="upd">Обновлено: 23.06.2026</p>
<p>Эти условия регулируют пользование сервисом «Подслушано в Нидерландах»
(Telegram-бот @podslushano_nl_bot), который предоставляет компания, указанная в
реквизитах внизу страницы.</p>

<h2>Услуги</h2>
<p>Гайд специалистов, доска объявлений, афиша мероприятий, отзывы, ИИ-ассистент и
личный кабинет специалиста для управления карточкой и подпиской.</p>

<h2>Правила использования</h2>
<ul>
 <li>указывайте достоверные данные и только те контакты, на которые имеете право;</li>
 <li>запрещены незаконный, оскорбительный, мошеннический контент и спам;</li>
 <li>не публикуйте чужие персональные данные без согласия владельца.</li>
</ul>
<p>Мы вправе проверять, отклонять, скрывать или удалять контент и ограничивать
доступ при нарушении правил.</p>

<h2>Размещение специалистов и кабинет</h2>
<p>Размещение карточки платное; цена и срок (месяц или год) указаны в боте и
включают BTW. Каждая заявка проходит проверку до публикации. Размещение
действует выбранный период и прекращается без продления новой оплатой; перед
окончанием мы пришлём напоминание. В личном кабинете специалист управляет своей
карточкой и подпиской; <b>каждая правка карточки вступает в силу только после
одобрения модератором</b>.</p>

<h2>Доска и афиша</h2>
<p>Объявления и мероприятия проходят модерацию. Часть опций (например, «поднять»
объявление или размещение в афише) платная — условия показаны в боте.</p>

<h2>Отзывы</h2>
<p>Отзывы должны быть честными и основанными на личном опыте. Мы можем удалять
фейковые, оскорбительные или вводящие в заблуждение отзывы.</p>

<h2>Оплата и счета</h2>
<p>Оплата проходит через Mollie (в т.ч. iDEAL, карты). Цены включают BTW 21%;
после оплаты мы присылаем счёт с разбивкой BTW на e-mail.</p>

<h2>Право на отказ и возвраты</h2>
<p>У бизнес-клиентов нет законного «права на отказ». У потребителей есть 14 дней
на отказ от договора; соглашаясь и запуская услугу сразу, вы даёте согласие на
немедленное исполнение. Если заявку отклонили — мы возвращаем сумму.</p>

<h2>Интеллектуальная собственность</h2>
<p>Бренд, оформление и материалы сервиса принадлежат нам. Присылая контент, вы
разрешаете показывать его в рамках сервиса; ответственность за этот контент
остаётся на вас.</p>

<h2>Ответственность</h2>
<p>Гайд и материалы носят информационный характер; мы не являемся стороной
договорённостей между пользователями и специалистами и не гарантируем результат.
Ответы ИИ — справочные и не заменяют профессиональную консультацию. Наша
ответственность ограничена суммой, которую вы оплатили за соответствующую услугу.</p>

<h2>Прекращение</h2>
<p>Мы можем приостановить или прекратить доступ при нарушении этих условий.</p>

<h2>Конфиденциальность</h2>
<p>Обработка персональных данных описана в нашей Политике конфиденциальности.</p>

<h2>Применимое право и споры</h2>
<p>Применяется право Нидерландов; споры рассматривает компетентный суд
Нидерландов. Жалобу можно направить нам на почту. Потребители из ЕС также могут
использовать платформу ЕС для разрешения споров онлайн (ODR):
<a href="https://ec.europa.eu/consumers/odr">ec.europa.eu/consumers/odr</a>.</p>

<h2>Изменения</h2>
<p>Мы можем обновлять эти условия; актуальная дата указана сверху.</p>
"""

_TERMS_NL = """
<h1>Algemene voorwaarden</h1>
<p class="upd">Laatst bijgewerkt: 23-06-2026</p>
<p>Deze voorwaarden gelden voor het gebruik van de dienst «Podslushano in
Nederland» (Telegram-bot @podslushano_nl_bot), aangeboden door het bedrijf
vermeld in de bedrijfsgegevens onderaan deze pagina.</p>

<h2>Diensten</h2>
<p>Specialistengids, prikbord, evenementenagenda, beoordelingen, AI-assistent en
een persoonlijk account voor specialisten om hun vermelding en abonnement te
beheren.</p>

<h2>Gebruiksregels</h2>
<ul>
 <li>verstrek juiste gegevens en alleen contactgegevens waarover je mag beschikken;</li>
 <li>onwettige, beledigende of frauduleuze inhoud en spam zijn verboden;</li>
 <li>plaats geen persoonsgegevens van anderen zonder hun toestemming.</li>
</ul>
<p>We mogen inhoud controleren, weigeren, verbergen of verwijderen en toegang
beperken bij overtreding.</p>

<h2>Vermeldingen en account</h2>
<p>Een vermelding is betaald; prijs en looptijd (maand of jaar) staan in de bot en
zijn inclusief btw. Elke aanvraag wordt vóór publicatie gecontroleerd. De
vermelding geldt voor de gekozen periode en stopt zonder verlenging via een nieuwe
betaling; vóór het einde sturen we een herinnering. In het account beheert de
specialist zijn vermelding en abonnement; <b>elke wijziging van de vermelding
wordt pas actief na goedkeuring door een moderator</b>.</p>

<h2>Prikbord en agenda</h2>
<p>Advertenties en evenementen worden gemodereerd. Sommige opties (zoals een
advertentie «omhoog» of plaatsing in de agenda) zijn betaald — de voorwaarden
staan in de bot.</p>

<h2>Beoordelingen</h2>
<p>Beoordelingen moeten eerlijk zijn en op eigen ervaring gebaseerd. We kunnen
valse, beledigende of misleidende beoordelingen verwijderen.</p>

<h2>Betaling en facturen</h2>
<p>Betalingen verlopen via Mollie (o.a. iDEAL, kaart). Prijzen zijn inclusief 21%
btw; na betaling sturen we een factuur met btw-specificatie per e-mail.</p>

<h2>Herroeping en restitutie</h2>
<p>Zakelijke klanten hebben geen wettelijk herroepingsrecht. Consumenten hebben in
beginsel 14 dagen herroepingsrecht; door akkoord te gaan en de dienst direct te
laten ingaan, stem je in met onmiddellijke uitvoering. Wordt je aanvraag afgewezen,
dan betalen we het bedrag terug.</p>

<h2>Intellectueel eigendom</h2>
<p>Het merk, de vormgeving en materialen van de dienst zijn van ons. Door inhoud in
te sturen geef je ons toestemming die binnen de dienst te tonen; je blijft zelf
verantwoordelijk voor die inhoud.</p>

<h2>Aansprakelijkheid</h2>
<p>De gids en materialen zijn informatief; wij zijn geen partij bij afspraken
tussen gebruikers en specialisten en garanderen geen resultaat. AI-antwoorden zijn
informatief en vervangen geen professioneel advies. Onze aansprakelijkheid is
beperkt tot het bedrag dat je voor de betreffende dienst hebt betaald.</p>

<h2>Beëindiging</h2>
<p>We kunnen toegang opschorten of beëindigen bij overtreding van deze voorwaarden.</p>

<h2>Privacy</h2>
<p>De verwerking van persoonsgegevens staat in onze Privacyverklaring.</p>

<h2>Toepasselijk recht en geschillen</h2>
<p>Nederlands recht is van toepassing; geschillen worden voorgelegd aan de bevoegde
Nederlandse rechter. Een klacht kun je ons mailen. EU-consumenten kunnen ook het
EU-platform voor onlinegeschillenbeslechting (ODR) gebruiken:
<a href="https://ec.europa.eu/consumers/odr">ec.europa.eu/consumers/odr</a>.</p>

<h2>Wijzigingen</h2>
<p>We kunnen deze voorwaarden bijwerken; de actuele datum staat bovenaan.</p>
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


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


def _slugify(name: str) -> str:
    """Чистый slug для коротких ссылок: «Fancy Beauty Space» → «fancy-beauty-space»,
    «Стилист Анна» → «stilist-anna». Транслитерируем кириллицу, остальное чистим."""
    out = []
    for ch in (name or "").strip().lower():
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isascii() and ch.isalnum():
            out.append(ch)
        elif ch in " _-/.,&":
            out.append("-")
    slug = re.sub(r"-+", "-", "".join(out)).strip("-")
    return slug or "spec"


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
            "id": s.id,
            "slug": _slugify(s.name),
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
    resp.headers["Cache-Control"] = "no-store"  # сайт должен брать всегда свежие данные
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


_CONTACT_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#eef2f8;margin:0;padding:24px;color:#222}}
 .wrap{{max-width:440px;margin:0 auto}} .top{{text-align:center;margin-bottom:12px}} .top img{{max-width:150px}}
 .card{{background:#fff;border-radius:14px;padding:16px 18px;box-shadow:0 6px 20px rgba(0,0,0,.07)}}
 .ph{{width:100%;max-height:300px;object-fit:cover;border-radius:10px;margin-bottom:8px}}
 .nm{{font-weight:700;font-size:18px}} .ds{{color:#555;margin:6px 0 10px;font-size:14px;line-height:1.5}}
 .lnks a{{display:inline-block;margin:4px 6px 0 0;padding:8px 13px;background:#2aabee;color:#fff;
  text-decoration:none;border-radius:10px;font-size:14px}}
 .more{{display:block;text-align:center;margin-top:16px;color:#2aabee;text-decoration:none}}
</style></head><body><div class="wrap"><div class="top">{logo}</div>{card}
 <a class="more" href="{guide}">Все специалисты в гайде →</a></div></body></html>"""


async def _contact_page(request: web.Request) -> web.Response:
    """Чистая короткая страница одного контакта: /c/<slug> или /s/<id>."""
    key = request.match_info.get("key", "")
    rows = await _active_specialists()
    target = None
    if key.isdigit():
        target = next((s for s in rows if s.id == int(key)), None)
    if target is None:
        target = next((s for s in rows if _slugify(s.name) == key.lower()), None)
    logo = f'<img src="{config.LOGO_URL}" alt="logo">' if config.LOGO_URL else ""
    guide = config.GUIDE_URL or "/guide"
    if target is None:
        body = '<div class="card"><div class="nm">Контакт не найден</div>' \
               '<div class="ds">Возможно, он снят с публикации.</div></div>'
        html_page = _CONTACT_PAGE.format(title="Контакт не найден", logo=logo, card=body, guide=guide)
        return web.Response(text=html_page, content_type="text/html", status=404)
    ratings = await ratings_for([specialist_key(target.name, target.contact)])
    badge = rating_badge(ratings.get(specialist_key(target.name, target.contact)))
    card = _guide_card(target, badge)
    html_page = _CONTACT_PAGE.format(title=target.name, logo=logo, card=card, guide=guide)
    return web.Response(text=html_page, content_type="text/html")


async def _ig_slide(request: web.Request) -> web.Response:
    """Отдаёт готовый слайд Instagram-карусели (нарисован ботом, лежит в памяти)."""
    from utils.slides import get_slide
    sid = request.match_info.get("sid", "").removesuffix(".jpg")
    data = get_slide(sid)
    if not data:
        return web.Response(status=404, text="not found")
    resp = web.Response(body=data, content_type="image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


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


# Эмодзи и пиктограммы (для очистки текста в фиде каталога на сайте)
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002190-\U000021FF"
    "\U00002300-\U000023FF\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F\U0000200D]+",
    flags=re.UNICODE,
)


def _clean(t: str) -> str:
    """Убирает эмодзи и схлопывает лишние пробелы (переносы строк сохраняет)."""
    t = _EMOJI_RE.sub("", t or "")
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip(" ·\t\n")


# Платформы онлайн-записи → ссылка показывается словом «Записаться»
_BOOKING_RE = re.compile(r"alteg\.io|altegio|yclients|dikidi|n-?bron|booking", re.I)


def _contacts_html(contact: str | None) -> str:
    """Готовые корректные ссылки контактов с понятными подписями (для сайта)."""
    if not contact:
        return ""
    links = parse_contact_links(contact)
    # сайт без http:// (www.…) parse не ловит — добавим вручную
    if not any(l["type"] == "website" for l in links):
        wm = re.search(r"\b(www\.[^\s·,)]+)", contact)
        if wm:
            links.append({"type": "website", "url": "https://" + wm.group(1).rstrip(".")})
    parts = []
    for l in links:
        t, url = l["type"], l["url"]
        if t == "whatsapp":
            continue  # не добавляем новых кнопок — номер ниже как «Позвонить»
        if t == "instagram":
            lab = "Instagram"
        elif t == "telegram":
            lab = "Telegram"
        elif t == "phone":
            pm = re.search(r"\+?\d[\d\s\-]{7,}\d", contact)
            lab = pm.group(0).strip() if pm else url.replace("tel:", "")
        elif t == "email":
            lab = url.replace("mailto:", "")
        elif t == "website":
            lab = "Записаться" if _BOOKING_RE.search(url) else "Сайт"
        else:
            lab = "Ссылка"
        parts.append(
            f'<a href="{html_lib.escape(url)}" target="_blank" rel="noopener">'
            f"{html_lib.escape(lab)}</a>"
        )
    return " · ".join(parts)


async def _api_guide(request: web.Request) -> web.Response:
    """JSON-фид для кастомного виджета каталога на сайте (KG_DATA_URL).

    Формат: массив [{name, desc, prov, cat}] — ровно то, что понимает виджет.
    Контакты идут в desc, виджет сам делает ссылки кликабельными.
    """
    rows = await _active_specialists()
    rows = sorted(rows, key=lambda s: (0 if s.is_premium else 1, s.category, s.name))
    data = []
    for s in rows:
        descr = _clean(s.description or "")
        # контакты — в одну строку через · (как было), отдельно от описания
        cparts = [_clean(p) for p in re.split(r"\s*·\s*|\n+", s.contact or "")]
        contact = " · ".join(p for p in cparts if p)
        # plain-версия (для поиска по карточкам)
        desc = "\n\n".join(p for p in [descr, contact] if p)
        # готовый HTML: описание + корректные ссылки контактов
        descr_html = html_lib.escape(descr).replace("\n", "<br>")
        contacts_html = _contacts_html(s.contact)
        if not contacts_html and contact:  # ссылок не нашли — покажем текст контактов
            contacts_html = html_lib.escape(contact)
        if descr_html and contacts_html:
            rich = descr_html + "<br><br>" + contacts_html
        else:
            rich = descr_html or contacts_html
        data.append({
            "id": s.id,
            "slug": _slugify(s.name),
            "name": _clean(s.name) or s.name,
            "desc": desc,
            "html": rich,
            "prov": "онлайн" if s.is_online else (s.province or ""),
            "cat": _SITE_GROUP.get(s.category, "Услуги"),
            "premium": bool(s.is_premium),
            "photo": _photo_url(s) or "",
        })
    resp = web.json_response(data)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "no-store"
    return resp


_ADS_CSS = """
:root{--accent:#e8722a;--accent-soft:#fbe9da;--ink:#26303a;--muted:#6b7682;
--bg:#fbf4ee;--card:#fff;--line:#ede3d9;--radius:18px;--free:#e9f6ec;--free-bd:#bfe3c6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;line-height:1.55}
.wrap{max-width:1080px;margin:0 auto;padding:40px 18px 60px}
h1{font-size:30px;text-align:center;margin:0 0 8px}
.sub{text-align:center;color:var(--accent);font-weight:600;margin-bottom:28px}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
padding:24px;position:relative}
.card.flag{border-color:var(--accent);box-shadow:0 10px 30px rgba(232,114,42,.10)}
.badge{position:absolute;top:-12px;left:22px;background:var(--accent);color:#fff;
font-size:12px;font-weight:700;padding:5px 12px;border-radius:20px}
.head{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.title{font-size:20px;font-weight:800;margin:0}
.price{font-size:20px;font-weight:800;color:var(--accent);white-space:nowrap}
.price small{display:block;font-size:12px;font-weight:600;color:var(--muted);text-align:right}
.lead{color:var(--muted);margin:8px 0 8px}
.opts{font-size:14px;color:var(--ink);margin:0 0 8px}.opts b{color:var(--accent)}
.faq{margin-top:34px}.faq h2{font-size:22px;margin:0 0 8px}
.faq details{border-bottom:1px solid var(--line);padding:10px 0}
.faq summary{cursor:pointer;font-weight:700}
.faq p{color:#444;margin:8px 0 0}
.contact{background:var(--accent-soft);border-radius:var(--radius);padding:20px;margin-top:24px;text-align:center}
.contact a{color:var(--accent);font-weight:700;text-decoration:none}
.guide{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:24px;margin-top:24px}
.guide h2{margin:0 0 8px;font-size:22px}.guide p{color:var(--muted);margin:6px 0}
.gcta{display:inline-block;margin-top:12px;background:var(--ink);color:#fff;text-decoration:none;padding:12px 18px;border-radius:12px;font-weight:700}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:0 0 6px}
@media(max-width:560px){.stats{grid-template-columns:repeat(2,1fr)}}
.stat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;text-align:center}
.snum{font-size:22px;font-weight:800;color:var(--accent)}
.slbl{font-size:13px;color:var(--muted);margin-top:2px}
.snote{text-align:center;color:var(--muted);font-size:12px;margin:6px 0 24px}
.card ul{margin:6px 0 0;padding-left:20px}.card li{margin:4px 0}
.who{color:var(--muted);font-size:14px;margin-top:12px}
.lbl{font-weight:700;margin:14px 0 6px}
.book{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
padding:24px;margin-top:34px}
.book h2{margin:0 0 6px;font-size:23px}
label{display:block;font-weight:700;margin:14px 0 6px}
select,input,textarea{width:100%;padding:12px;border:1px solid var(--line);border-radius:12px;
font-size:16px;background:#fff;color:var(--ink)}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:560px){.row2{grid-template-columns:1fr}}
.seg{display:flex;gap:10px;margin-top:6px}
.seg label{flex:1;margin:0;border:1px solid var(--line);border-radius:12px;padding:12px;
text-align:center;cursor:pointer;font-weight:600}
.seg input{display:none}.seg input:checked+span{color:var(--accent)}
.seg label:has(input:checked){border-color:var(--accent);background:var(--accent-soft)}
button{margin-top:22px;width:100%;background:var(--accent);color:#fff;border:0;
padding:15px;border-radius:12px;font-weight:800;font-size:17px;cursor:pointer}
.err{background:#fde8e8;color:#a12;padding:10px 14px;border-radius:10px;margin:12px 0}
.note{color:var(--muted);font-size:13px;margin-top:12px}
.cal{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:8px}
@media(max-width:820px){.cal{grid-template-columns:1fr}}
.mon h4{margin:0 0 6px;text-align:center;font-size:15px}
.days{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}
.dh{font-size:11px;color:var(--muted);text-align:center;padding:2px 0}
.d{aspect-ratio:1;display:flex;align-items:center;justify-content:center;
border-radius:8px;font-size:13px;user-select:none}
.d.off{color:#c8cdd2}
.d.taken{background:#f3eee9;color:#bcae9f;text-decoration:line-through}
.d.free{background:var(--free);border:1px solid var(--free-bd);cursor:pointer;font-weight:600}
.d.free:hover{filter:brightness(.97)}
.d.sel{background:var(--accent);color:#fff;border-color:var(--accent)}
.legend{display:flex;gap:16px;font-size:13px;color:var(--muted);margin:10px 0 0;flex-wrap:wrap}
.legend i{display:inline-block;width:14px;height:14px;border-radius:4px;vertical-align:-2px;margin-right:5px}
.sum{background:var(--accent-soft);border-radius:12px;padding:12px 14px;margin-top:16px;font-weight:600}
details.terms{margin-top:16px;border:1px solid var(--line);border-radius:12px;padding:8px 14px}
details.terms summary{cursor:pointer;color:var(--accent);font-weight:700;padding:6px 0}
details.terms h5{margin:12px 0 2px;font-size:14px}details.terms p{margin:0 0 8px;font-size:13px;color:#444}
.chk{display:flex;gap:10px;align-items:flex-start;margin-top:14px;font-size:14px}
.chk input{width:auto;margin-top:3px}
"""

_WD_HEAD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_MON_NAMES = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
              "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]


def _calendar_html(taken: set) -> str:
    """3 месяца от текущего: свободные/занятые/недоступные дни."""
    import calendar as _cal
    from datetime import date as _date, timedelta as _td
    today = _date.today()
    lo, hi = today + _td(days=1), today + _td(days=90)
    months = []
    y, m = today.year, today.month
    for _ in range(3):
        weeks = _cal.Calendar(firstweekday=0).monthdayscalendar(y, m)
        heads = "".join(f'<div class="dh">{w}</div>' for w in _WD_HEAD)
        cells = []
        for week in weeks:
            for dnum in week:
                if dnum == 0:
                    cells.append('<div class="d off"></div>')
                    continue
                d = _date(y, m, dnum)
                iso = d.isoformat()
                if d < lo or d > hi:
                    cells.append(f'<div class="d off">{dnum}</div>')
                elif iso in taken:
                    cells.append(f'<div class="d taken">{dnum}</div>')
                else:
                    cells.append(f'<div class="d free" data-date="{iso}">{dnum}</div>')
        months.append(
            f'<div class="mon"><h4>{_MON_NAMES[m]} {y}</h4>'
            f'<div class="days">{heads}{"".join(cells)}</div></div>'
        )
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return f'<div class="cal">{"".join(months)}</div>'


def _ads_html(taken: set, error: str = "") -> str:
    import json
    cards = []
    for key, f in config.AD_FORMATS.items():
        badge = f'<span class="badge">{html_lib.escape(f["badge"])}</span>' if f.get("badge") else ""
        flag = " flag" if key == "expert" else ""
        opts = f["options"]
        head_price = f'от €{opts[0]["price"]}' if len(opts) > 1 else f'€{opts[0]["price"]}'
        opts_line = (
            '<div class="opts">'
            + " · ".join(f'<b>€{o["price"]}</b> — {html_lib.escape(o["label"])}' for o in opts)
            + "</div>" if len(opts) > 1 else "")
        addon_line = (
            f'<div class="opts">доп.: <b>+€{f["addon"]["price"]}</b> — '
            f'{html_lib.escape(f["addon"]["label"])}</div>' if f.get("addon") else "")
        bullets = "".join(f"<li>{html_lib.escape(b)}</li>" for b in f.get("details", []))
        cards.append(
            f'<div class="card{flag}">{badge}<div class="head">'
            f'<h3 class="title">{html_lib.escape(f["name"])}</h3>'
            f'<div class="price">{head_price}</div></div>'
            f'<p class="lead">{html_lib.escape(f["lead"])}</p>{opts_line}{addon_line}'
            f'<div class="lbl">Что входит:</div><ul>{bullets}</ul>'
            f'<div class="who"><b>Кому подходит:</b> {html_lib.escape(f["who"])}.</div></div>'
        )
    fmt_opts = "".join(f'<option value="{k}">{html_lib.escape(f["name"])}</option>'
                       for k, f in config.AD_FORMATS.items())
    fmap = {k: {"name": f["name"], "options": f["options"], "addon": f.get("addon"),
                "dates": f.get("dates", 1)}
            for k, f in config.AD_FORMATS.items()}
    faq_html = "".join(
        f"<details><summary>{html_lib.escape(q)}</summary><p>{html_lib.escape(a)}</p></details>"
        for q, a in config.AD_FAQ)
    contact_html = (
        '<div class="contact">Остались вопросы? Напишите нам — '
        f'<a href="{config.BOT_URL}">Telegram</a> · '
        '<a href="https://instagram.com/podslushano.nl">Instagram</a> · '
        f'<a href="mailto:{config.COMPANY_EMAIL}">{config.COMPANY_EMAIL}</a></div>')
    _cur = config.LISTING_CURRENCY
    guide_html = (
        '<div class="guide"><h2>Гайд специалистов</h2>'
        '<p>Не разовая реклама, а постоянное присутствие: ваша карточка в нашем '
        'каталоге специалистов — вас находят те, кто прямо сейчас ищет услугу. '
        'Поиск по категориям, отзывы, продвижение.</p>'
        f'<p><b>Размещение от {config.LISTING_PRICE_MONTH} {_cur}/мес или '
        f'{config.LISTING_PRICE_YEAR} {_cur}/год.</b> Премиум — выше в выдаче и с бейджем.</p>'
        f'<a class="gcta" href="{config.BOT_URL}">Добавиться в гайд — в боте →</a></div>')
    stats_html = (
        '<div class="stats">'
        + "".join(f'<div class="stat"><div class="snum">{html_lib.escape(n)}</div>'
                  f'<div class="slbl">{html_lib.escape(l)}</div></div>'
                  for n, l in config.AD_STATS)
        + '</div>'
        f'<div class="snote">Данные аудитории на {html_lib.escape(config.AD_STATS_UPDATED)}</div>')
    terms_html = (
        f"<p><b>Исполнитель:</b><br>{config.ad_company_block_html()}</p>"
        + "".join(f"<h5>{html_lib.escape(t)}</h5><p>{html_lib.escape(b)}</p>"
                  for t, b in config.AD_TERMS)
    )
    err = f'<div class="err">{html_lib.escape(error)}</div>' if error else ""
    cal = _calendar_html(taken)
    fmap_js = json.dumps(fmap, ensure_ascii=False)
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Реклама — Podslushano.nl</title><style>{_ADS_CSS}</style></head><body>
<div class="wrap">
<h1>Реклама на Podslushano.nl</h1>
<div class="sub">Нативное продвижение для услуг, экспертов и мероприятий в Нидерландах</div>
{stats_html}
<div class="grid">{''.join(cards)}</div>

{guide_html}

<div class="book"><h2>Забронировать дату и формат</h2>{err}
<form method="post" action="/ads/book" id="bf">
  <label>Формат</label>
  <select name="fmt" id="fmt">{fmt_opts}</select>
  <label>Длительность / вариант</label>
  <select name="opt" id="opt"></select>
  <label class="chk" id="addonRow" style="display:none"><input type="checkbox" name="addon" id="addon"><span id="addonLbl"></span></label>

  <label>Выберите свободную дату</label>
  {cal}
  <div class="legend">
    <span><i style="background:var(--free);border:1px solid var(--free-bd)"></i>свободно</span>
    <span><i style="background:#f3eee9"></i>занято</span>
    <span><i style="background:var(--accent)"></i>выбрано</span>
  </div>
  <input type="hidden" name="dates" id="dates">

  <label>Кто оплачивает</label>
  <div class="seg">
    <label><input type="radio" name="client_type" value="person" checked><span>Физлицо</span></label>
    <label><input type="radio" name="client_type" value="business"><span>Компания</span></label>
  </div>
  <div class="note">Все данные для счёта вводите латиницей, как в документах (напр. Alex Mair).</div>

  <div id="gPerson">
    <label>Имя и фамилия</label>
    <input name="buyer_name" placeholder="Иван Иванов">
  </div>
  <div id="gBusiness" style="display:none">
    <label>Название компании</label><input name="company" placeholder="Bedrijf B.V.">
    <div class="row2">
      <div><label>BTW-номер (необязательно)</label><input name="btw" placeholder="NL000000000B00"></div>
      <div><label>KVK-номер (необязательно)</label><input name="kvk" placeholder="12345678"></div>
    </div>
    <label>Телефон (необязательно)</label><input name="phone" placeholder="+31 6 ...">
  </div>

  <div class="row2">
    <div><label>Адрес</label><input name="address" placeholder="Straat 1, Stad" required></div>
    <div id="gPost" style="display:none"><label>Почтовый индекс</label><input name="postcode" placeholder="1234 AB"></div>
  </div>
  <label>E-mail для счёта</label>
  <input type="email" name="email" placeholder="mail@example.com" required>

  <div class="sum" id="sum">Выберите формат и дату.</div>

  <details class="terms"><summary>Условия сотрудничества</summary>{terms_html}</details>
  <label class="chk"><input type="checkbox" name="terms" id="terms" required>
    <span>Я ознакомился(ась) и принимаю условия сотрудничества. Оплата означает полное согласие с ними.</span></label>

  <button type="submit">Перейти к оплате</button>
  <div class="note">Оплата через Mollie (iDEAL, карты). 100% предоплата, дата
    фиксируется только после оплаты. Счёт (factuur) придёт на e-mail. Все цены включают BTW 21%.</div>
</form></div>

<div class="faq"><h2>Частые вопросы</h2>{faq_html}</div>
{contact_html}
</div>
<script>
const F={fmap_js};
const fmt=document.getElementById('fmt'),opt=document.getElementById('opt'),
datesI=document.getElementById('dates'),sum=document.getElementById('sum'),
addon=document.getElementById('addon'),addonRow=document.getElementById('addonRow'),
addonLbl=document.getElementById('addonLbl');
let sel=[],need=1;
function fillOpt(){{opt.innerHTML='';F[fmt.value].options.forEach(o=>{{
  const e=document.createElement('option');e.value=o.key;e.textContent=o.label+' — €'+o.price;
  e.dataset.price=o.price;opt.appendChild(e);}});
  const a=F[fmt.value].addon;
  if(a){{addonRow.style.display='flex';addonLbl.textContent=a.label+' (+€'+a.price+')';addon.dataset.price=a.price;}}
  else{{addonRow.style.display='none';addon.checked=false;}}
  need=F[fmt.value].dates||1;sel=[];datesI.value='';
  document.querySelectorAll('.d.sel').forEach(x=>x.classList.remove('sel'));
  updateSum();}}
function updateSum(){{const o=opt.selectedOptions[0];
  let p=o?parseFloat(o.dataset.price):0;
  if(addon.checked&&F[fmt.value].addon)p+=parseFloat(addon.dataset.price);
  const dt=sel.length?sel.join(', '):('выберите '+need+(need>1?' даты':' дату'));
  sum.textContent=F[fmt.value].name+(o?' · '+o.textContent:'')+(addon.checked&&F[fmt.value].addon?' + повтор':'')+' · '+dt+' · €'+p.toFixed(2);}}
fmt.onchange=fillOpt;opt.onchange=updateSum;addon.onchange=updateSum;
document.querySelectorAll('.d.free').forEach(c=>c.onclick=()=>{{
  const ds=c.dataset.date,i=sel.indexOf(ds);
  if(i>-1){{sel.splice(i,1);c.classList.remove('sel');}}
  else{{
    if(sel.length>=need){{
      if(need===1){{document.querySelectorAll('.d.sel').forEach(x=>x.classList.remove('sel'));sel=[];}}
      else{{alert('Нужно выбрать '+need+' даты. Сначала снимите лишнюю.');return;}}
    }}
    sel.push(ds);c.classList.add('sel');
  }}
  datesI.value=sel.join(',');updateSum();}});
function toggleType(){{const b=document.querySelector('input[name=client_type]:checked').value==='business';
  document.getElementById('gBusiness').style.display=b?'block':'none';
  document.getElementById('gPerson').style.display=b?'none':'block';
  document.getElementById('gPost').style.display=b?'block':'none';
  document.querySelector('[name=buyer_name]').required=!b;
  ['company','postcode'].forEach(n=>document.querySelector('[name='+n+']').required=b);}}
document.querySelectorAll('input[name=client_type]').forEach(r=>r.onchange=toggleType);
document.getElementById('bf').onsubmit=e=>{{if(sel.length!==need){{e.preventDefault();
  alert('Выберите '+need+(need>1?' даты в календаре (минимум 14 дней между ними).':' дату в календаре.'));}}}};
fillOpt();toggleType();
</script>
</body></html>"""


async def _ads(request: web.Request) -> web.Response:
    from handlers.ads import _taken
    return web.Response(text=_ads_html(await _taken()), content_type="text/html")


async def _ads_book(request: web.Request) -> web.Response:
    from handlers.ads import book_and_pay, _taken
    data = await request.post()
    fields = {k: (data.get(k) or "").strip() for k in (
        "email", "buyer_name", "company", "btw", "kvk", "address", "postcode", "phone")}
    fields["client_type"] = data.get("client_type")
    fields["terms"] = bool(data.get("terms"))
    fields["addon"] = bool(data.get("addon"))
    dates = [s.strip() for s in (data.get("dates") or "").split(",") if s.strip()]
    checkout, err = await book_and_pay(
        (data.get("fmt") or "").strip(), (data.get("opt") or "").strip(),
        dates, fields)
    if checkout:
        raise web.HTTPFound(location=checkout)
    return web.Response(
        text=_ads_html(await _taken(), error=err or "Не удалось оформить бронь."),
        content_type="text/html", status=400)


def _reklama_html(error: str = "") -> str:
    stats = "".join(
        f'<div class="stat"><div class="snum">{html_lib.escape(n)}</div>'
        f'<div class="slbl">{html_lib.escape(l)}</div></div>' for n, l in config.AD_STATS)
    formats = " · ".join(html_lib.escape(f["name"]) for f in config.AD_FORMATS.values())
    err = f'<div class="err">{html_lib.escape(error)}</div>' if error else ""
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Реклама — Podslushano.nl</title><style>{_ADS_CSS}</style></head><body>
<div class="wrap">
<h1>Реклама в Podslushano.nl</h1>
<div class="sub">Доходим до русскоязычных в Нидерландах — нативно, без рекламного шума</div>
<div class="stats">{stats}</div>
<div class="snote">Данные аудитории на {html_lib.escape(config.AD_STATS_UPDATED)}</div>
<div class="guide"><h2>Что мы можем</h2>
<p>Форматы: {formats}. Подберём под вашу задачу индивидуально — расскажите, что
хотите прорекламировать, и мы пришлём форматы и условия.</p></div>
<div class="book"><h2>Оставить заявку</h2>{err}
<form method="post" action="/reklama/submit">
  <label>Имя</label><input name="name" required>
  <label>Бизнес / проект</label><input name="business" placeholder="Название" required>
  <label>Instagram</label><input name="instagram" placeholder="@username или ссылка">
  <label>Telegram</label><input name="telegram" placeholder="@username или ссылка">
  <div class="note">Укажите хотя бы один — Instagram или Telegram (второй по желанию).</div>
  <label>Что хотите прорекламировать?</label>
  <textarea name="message" rows="3" placeholder="Кратко о задаче"></textarea>
  <button type="submit">Отправить заявку</button>
  <div class="note">Мы свяжемся с вами и пришлём форматы и условия под вашу задачу.</div>
</form></div>
</div>
<script>
document.querySelector('form').onsubmit=function(e){{
  var ig=document.querySelector('[name=instagram]').value.trim();
  var tg=document.querySelector('[name=telegram]').value.trim();
  if(!ig&&!tg){{e.preventDefault();alert('Укажите хотя бы один контакт — Instagram или Telegram.');}}
}};
</script>
</body></html>"""


def _reklama_thanks() -> str:
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Заявка отправлена</title><style>{_ADS_CSS}</style></head><body>
<div class="wrap"><h1>Спасибо! 🙌</h1>
<div class="sub">Заявка получена</div>
<div class="guide"><p>Мы свяжемся с вами в ближайшее время и пришлём форматы и
условия под вашу задачу.</p>
<a class="gcta" href="{config.SITE_URL}">На сайт Podslushano.nl →</a></div>
</div></body></html>"""


async def _reklama(request: web.Request) -> web.Response:
    return web.Response(text=_reklama_html(), content_type="text/html")


async def _reklama_submit(request: web.Request) -> web.Response:
    data = await request.post()
    name = (data.get("name") or "").strip()
    business = (data.get("business") or "").strip()
    ig = (data.get("instagram") or "").strip()
    tg = (data.get("telegram") or "").strip()
    message = (data.get("message") or "").strip()
    if not name or not (ig or tg):
        return web.Response(
            text=_reklama_html("Укажите имя и хотя бы один контакт — Instagram или Telegram."),
            content_type="text/html", status=400)
    contact = " · ".join(p for p in (
        f"Instagram: {ig}" if ig else "", f"Telegram: {tg}" if tg else "") if p)
    async with get_session() as session:
        session.add(AdLead(name=name, business=business or None,
                           contact=contact, message=message or None))
        await session.commit()
    bot = request.app["bot"]
    txt = ("📨 <b>Новая заявка на рекламу</b>\n\n"
           f"Имя: {html_lib.escape(name)}\n"
           f"Бизнес: {html_lib.escape(business or '—')}\n"
           f"Контакт: {html_lib.escape(contact)}\n"
           f"Сообщение: {html_lib.escape(message or '—')}")
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, txt)
        except Exception as e:  # noqa: BLE001
            log.warning("Не уведомил админа о заявке: %s", e)
    return web.Response(text=_reklama_thanks(), content_type="text/html")


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
    app.router.add_get("/ig-slide/{sid}", _ig_slide)
    app.router.add_get("/api/specialists.json", _api_specialists)
    app.router.add_get("/api/guide.json", _api_guide)
    app.router.add_get("/c/{key}", _contact_page)   # короткая ссылка по slug
    app.router.add_get("/s/{key}", _contact_page)   # короткая ссылка по id
    app.router.add_get("/ads", _ads)            # приватная страница брони с ценами
    app.router.add_post("/ads/book", _ads_book)  # оформление брони → оплата Mollie
    app.router.add_get("/reklama", _reklama)            # публичная заявка на рекламу (без цен)
    app.router.add_post("/reklama/submit", _reklama_submit)
    app.router.add_post("/mollie-webhook", _mollie_webhook)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    log.info("Веб-сервер запущен на порту %s", config.PORT)
    return runner
