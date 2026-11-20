"""Public author application for podslushano.nl: questionnaire, NDA and contributor terms.

/authors/agreement — анкета автора (о себе) + соглашение о неразглашении + условия участия.
/authors/nda и /authors/terms — те же документы отдельными страницами (прочитать или сохранить).
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re

from aiohttp import web
from sqlalchemy import func, select

import config
from database.db import get_session
from database.models import AuthorAgreementAcceptance

log = logging.getLogger(__name__)

AGREEMENT_VERSION = "1.2"
AGREEMENT_DATE = "20.11.2026"
NDA_VERSION = "1.0"
NDA_DATE = "20.11.2026"
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

_OPERATOR_NAME = "Aleksei Maksimovich Egorov"
_KVK = "98882317"
_BTW = "NL005359099B74"
_ADDRESS = "Karel Doormanstraat 63, 5342 TJ Oss, Nederland"
_EMAIL = config.COMPANY_EMAIL
_SITE = "https://www.podslushano.nl"

# ---------------------------------------------------------------------------
# Условия участия (канонический текст для хэша) — версия 1.2:
# п. 8 ссылается на отдельное соглашение о неразглашении, п. 14 перечисляет ответы анкеты.
# ---------------------------------------------------------------------------
_AGREEMENT_CANONICAL = f"""
podslushano.nl Independent Contributor Terms v{AGREEMENT_VERSION} dated {AGREEMENT_DATE}.
Operator: {_OPERATOR_NAME}; KVK {_KVK}; BTW {_BTW}; {_ADDRESS}; {_EMAIL}.

1. Application and scope.
Submitting the form records acceptance of these terms. It does not automatically admit the applicant to
the author pool, create employment, guarantee assignments, compensation or income. If podslushano.nl
accepts the applicant as a contributor, these terms govern the ongoing contributor relationship unless
a separate written agreement for a specific assignment says otherwise.

2. Independent contributor relationship.
The parties intend an independent contributor relationship, not an employment contract. There are no
fixed working hours, shifts, minimum output, duty to remain available, salary, holiday allowance or
guaranteed volume of work. The contributor may work for other clients and projects. Mandatory law and
the actual way the parties work always prevail over labels used in this agreement.

3. Autonomy and instructions.
The contributor decides whether to propose content and whether to accept each assignment. After accepting
an assignment, the contributor independently decides how and when to perform the work and normally uses
their own phone/equipment. podslushano.nl may define the intended result: subject, deliverables, platform,
technical or brand requirements, deadline and a location where the nature of the assignment requires it.
podslushano.nl does not direct the contributor's day-to-day working method, hours or work process.

4. Voluntary editorial content.
Stories, video, photos, observations and local reports proposed by the contributor are voluntary. There
is no required publication frequency. Organic/editorial content is unpaid unless payment is expressly
agreed before the work is accepted.

5. Events and invitations.
podslushano.nl may offer tickets, invitations, accreditation or access to events. Availability is not
guaranteed. A ticket or invitation is primarily access needed for the event and is not a recurring wage.
If podslushano.nl expects content in return, the expected result is agreed before the contributor accepts.

6. Paid assignments.
Each commercial or otherwise paid task is offered separately. Before acceptance, the parties agree at
least the intended result/deliverables, deadline and contributor fee. The contributor may accept or refuse
without affecting their ability to propose voluntary content. There is no guarantee of recurring paid work.
Before the first payment, podslushano.nl may request invoice, KVK/BTW or other information required for
lawful payment, bookkeeping or reporting, depending on the contributor's status.

7. Editorial and commercial control.
podslushano.nl decides whether submitted content is published, where it is published, how it is edited or
formatted, and manages advertiser negotiations, prices, campaigns, brand standards and access permissions.
This control concerns the publication/result and podslushano.nl business decisions, not supervision of the
contributor's independent work process.

8. Confidentiality.
Confidentiality is governed by the separate podslushano.nl Author Non-Disclosure Agreement v{NDA_VERSION}
dated {NDA_DATE}, accepted together with these terms. Internal chat content, the identity of anonymous senders,
personal data of community members, advertiser and partner contacts obtained through the project, pricing,
discounts, commercial terms, analytics, unpublished plans, workflows, access credentials and internal feedback
are confidential and may not be shared outside the team without permission. The duty continues for 24 months
after cooperation ends for non-public commercial and operational information, and without time limit for the
identity of anonymous senders and personal data of community members.

9. Non-circumvention.
For 12 months after the contributor's last work with a specific advertiser or partner first introduced
through podslushano.nl, the contributor will not knowingly bypass podslushano.nl to solicit or contract
directly with that contact for substantially similar advertising services without written permission.
This does not apply to relationships demonstrably existing before the introduction by podslushano.nl.

10. Own projects.
The contributor may run personal social media, build a personal brand, work for others and earn independently,
provided they do not misuse podslushano.nl confidential information, access, brand assets or project-originated
commercial relationships.

11. Content rights.
The contributor confirms they have the right to submit the content. By submitting content specifically for
podslushano.nl, the contributor grants podslushano.nl a non-exclusive, worldwide, royalty-free licence to edit,
format, publish, repost and archive that content across podslushano.nl channels and materials promoting the
project. Content created for a paid campaign may also be used by the relevant advertiser within the campaign
scope agreed for that assignment.

12. Access and representation.
Access is role-based and may be changed or withdrawn at any time. Passwords, master/admin access, CRM, full
client lists and financial information are not automatically provided. The contributor may describe themselves
as a podslushano.nl author while actively participating, but may not bind podslushano.nl, quote commercial prices
or present themselves as owner or authorized commercial representative unless explicitly authorized.

13. Ending cooperation.
Either side may stop the contributor relationship at any time. Accepted paid assignments are completed or
closed by mutual agreement. Project access may be revoked immediately when cooperation ends. Unpublished
confidential materials and access data must not be retained or used after exit.

14. Data and law.
podslushano.nl stores the applicant's name, city, email, Telegram, optional Instagram, phone model, questionnaire
answers (time in the Netherlands, occupation, languages, preferred formats and topics, experience, portfolio
links, on-camera and travel preferences, indicative frequency, referral source and free-text answers), the
versions and hashes of these terms and of the Non-Disclosure Agreement, the acceptance timestamp and technical
user-agent data for application administration and evidence of acceptance. Financial and tax data may be
retained where legally required. The applicant may request access, correction or deletion at {_EMAIL}, unless
the law requires retention. Dutch law applies. The parties first try to resolve disputes informally; if that
fails, the competent court in the Netherlands has jurisdiction, subject to mandatory law.
""".strip()

AGREEMENT_SHA256 = hashlib.sha256(_AGREEMENT_CANONICAL.encode("utf-8")).hexdigest()

# ---------------------------------------------------------------------------
# Соглашение о неразглашении. Один источник: из него собираются и страница, и текст для хэша,
# поэтому хэш всегда соответствует ровно тому, что человек прочитал. Строка с «• » — пункт списка.
# ---------------------------------------------------------------------------
NDA_TITLE = "Соглашение о неразглашении для авторов podslushano.nl"

_NDA_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("1. Стороны и зачем это нужно", (
        f"Соглашение заключается между оператором проекта podslushano.nl — {_OPERATOR_NAME} "
        f"(KVK {_KVK}, BTW {_BTW}, {_ADDRESS}) — и автором, который отправляет анкету.",
        "Люди доверяют podslushano.nl свои истории, вопросы и личные ситуации, часто анонимно. "
        "Участвуя в сообществе авторов, автор может узнать то, что не предназначено для публики. "
        "Соглашение защищает этих людей, участников сообщества и сам проект.",
        "Соглашение действует с момента отправки анкеты, в том числе пока заявка рассматривается, "
        "и не зависит от того, будет ли автор принят в пул авторов.",
    )),
    ("2. Что считается конфиденциальной информацией", (
        "Конфиденциальная информация — любая непубличная информация, которую автор получает через "
        "podslushano.nl в любой форме: в чатах, устно, на встречах, в файлах, скриншотах, письмах "
        "или через выданные доступы. В частности:",
        "• личность, контакты и любые данные, по которым можно узнать людей, приславших анонимные "
        "истории, вопросы, фото или видео;",
        "• неопубликованные истории, материалы, черновики, планы публикаций, рубрик и проектов;",
        "• содержимое закрытых чатов авторов и команды: сообщения, голосовые, фото, видео и файлы;",
        "• персональные данные участников сообщества, подписчиков, героев материалов и других авторов: "
        "имена, телефоны, адреса, переписка;",
        "• контакты рекламодателей и партнёров, цены, скидки, условия сделок, статистика и аналитика аккаунтов;",
        "• пароли, коды, токены, служебные ссылки и доступы к аккаунтам и инструментам;",
        "• внутренние процессы, решения по модерации, редакционная обратная связь и обсуждения внутри команды.",
    )),
    ("3. Что не считается конфиденциальным", (
        "Обязательство не распространяется на информацию, которая:",
        "• уже опубликована podslushano.nl или стала общедоступной не по вине автора;",
        "• была законно известна автору до того, как он получил её через проект;",
        "• получена автором законно от третьего лица, которое не было обязано хранить её в тайне.",
        "Если раскрыть информацию требует закон, суд или государственный орган, автор раскрывает только "
        "необходимый минимум и, если это законно, заранее сообщает об этом podslushano.nl.",
    )),
    ("4. Что автор обязуется делать", (
        "• использовать конфиденциальную информацию только для работы над материалами и задачами podslushano.nl;",
        "• не передавать её третьим лицам — в том числе друзьям, родственникам, другим блогерам, пабликам и СМИ — "
        "без явного разрешения podslushano.nl, данного письменно или в мессенджере;",
        "• не делать скриншоты, записи экрана, пересылки и копии из закрытых чатов для передачи за пределы команды;",
        "• не публиковать неопубликованные материалы проекта и других авторов, а также планы и анонсы podslushano.nl "
        "до их официальной публикации;",
        "• не пытаться выяснить личность анонимного отправителя, не связываться с ним напрямую в обход проекта "
        "и не раскрывать его личность, даже если узнал её случайно;",
        "• хранить файлы и доступы на защищённых устройствах и никому не передавать пароли и коды;",
        "• сразу сообщить podslushano.nl, если информация могла попасть к посторонним: потерян телефон, "
        "сообщение переслано по ошибке, взломан аккаунт.",
    )),
    ("5. Персональные данные", (
        "Если в ходе работы автор получает персональные данные других людей, он обрабатывает их только в рамках "
        "задачи podslushano.nl и по правилам общего регламента ЕС о защите данных (AVG/GDPR): не хранит дольше, "
        "чем нужно для задачи, не использует в своих целях и не передаёт дальше.",
    )),
    ("6. Сколько действует соглашение", (
        "Соглашение действует всё время участия автора в проекте.",
        "После окончания сотрудничества непубличную коммерческую и операционную информацию нельзя разглашать "
        "ещё 24 месяца.",
        "Личность анонимных отправителей и персональные данные участников сообщества нельзя раскрывать бессрочно.",
    )),
    ("7. Когда сотрудничество заканчивается", (
        "Автор выходит из закрытых чатов, удаляет или возвращает непубличные материалы, файлы и доступы, полученные "
        "через проект, и больше их не использует. Исключение — информация, которую автор обязан хранить по закону.",
        "Собственные опубликованные работы автор может оставить себе и показывать в портфолио.",
    )),
    ("8. Что соглашение не запрещает", (
        "• рассказывать в общих чертах, что автор участвует или участвовал в podslushano.nl, и показывать свои "
        "опубликованные работы;",
        "• вести свои соцсети, работать с другими проектами и заказчиками, если при этом не используется "
        "конфиденциальная информация;",
        "• сообщать о возможных нарушениях закона в компетентные органы, в том числе по нидерландскому закону "
        "о защите информаторов (Wet bescherming klokkenluiders).",
    )),
    ("9. Если соглашение нарушено", (
        "podslushano.nl вправе сразу прекратить сотрудничество и закрыть все доступы, потребовать прекратить "
        "нарушение и удалить разглашённую информацию, а также требовать возмещения причинённого ущерба "
        "по законодательству Нидерландов.",
    )),
    ("10. Право и связь с другими документами", (
        "Соглашение действует вместе с условиями участия авторов podslushano.nl. Если по вопросам "
        "конфиденциальности они расходятся, приоритет у этого соглашения.",
        "Применяется право Нидерландов. Сначала стороны стараются решить спор напрямую; если не получилось, "
        "спор рассматривает компетентный суд Нидерландов. Вопросы по соглашению — на " + _EMAIL + ".",
    )),
)


def _nda_canonical() -> str:
    lines = [f"{NDA_TITLE}. Версия {NDA_VERSION} от {NDA_DATE}."]
    for title, paragraphs in _NDA_SECTIONS:
        lines.append("")
        lines.append(title)
        lines.extend(paragraphs)
    return "\n".join(lines)


NDA_SHA256 = hashlib.sha256(_nda_canonical().encode("utf-8")).hexdigest()

# ---------------------------------------------------------------------------
# Анкета: варианты ответов (код в форме → подпись, которая сохраняется в базе)
# ---------------------------------------------------------------------------
_YEARS_NL = (("lt1", "Меньше года"), ("1-3", "1–3 года"), ("3-5", "3–5 лет"), ("5plus", "Больше 5 лет"))
_LANGUAGES = (("ru", "Русский"), ("uk", "Украинский"), ("en", "Английский"), ("nl", "Нидерландский"),
              ("other", "Другой"))
_FORMATS = (
    ("stories", "Сторис и короткие видео"), ("photo", "Фото"), ("texts", "Тексты и статьи"),
    ("events", "Репортажи с событий"), ("reviews", "Обзоры мест, кафе и магазинов"),
    ("people", "Интервью и истории людей"), ("news", "Новости и переводы с нидерландского"),
    ("other", "Другое"),
)
_TOPICS = (
    ("afisha", "События и афиша"), ("food", "Еда, кафе, рестораны"), ("life", "Быт, документы, бюрократия"),
    ("work", "Работа и карьера"), ("family", "Дети и семья"), ("travel", "Путешествия по Нидерландам"),
    ("shopping", "Шопинг и выгодные покупки"), ("sport", "Спорт и активный отдых"),
    ("culture", "Культура и искусство"), ("housing", "Жильё"),
)
_EXPERIENCE = (
    ("none", "Пока нет — хочу попробовать"), ("personal", "Веду личные соцсети"),
    ("blog", "Вёл(а) блог или делал(а) контент для других"),
    ("pro", "Профессионально: журналистика, SMM, фото или видео"),
)
_ON_CAMERA = (("yes", "Да, спокойно"), ("sometimes", "Иногда, если нужно"), ("no", "Предпочитаю быть за кадром"))
_TRAVEL = (("city", "Только в своём городе"), ("region", "В своём регионе"), ("country", "По всей стране"))
_FREQUENCY = (("monthly", "Пару раз в месяц"), ("weekly", "Примерно раз в неделю"),
              ("often", "Несколько раз в неделю"), ("free", "По настроению, без графика"))
_SOURCE = (("instagram", "Instagram"), ("telegram", "Telegram"), ("tiktok", "TikTok"),
           ("site", "Сайт podslushano.nl"), ("friends", "От друзей или знакомых"), ("other", "Другое"))

# Текстовые поля: имя → (подпись для сообщения об ошибке, максимальная длина, обязательно ли)
_TEXT_FIELDS = {
    "full_name": ("ФИО", 200, True),
    "city": ("город", 120, True),
    "email": ("e-mail", 200, True),
    "telegram": ("Telegram", 200, True),
    "instagram": ("Instagram", 200, False),
    "phone_model": ("телефон для съёмки", 120, True),
    "occupation": ("чем занимаешься", 200, False),
    "about": ("о себе", 2000, True),
    "portfolio": ("примеры работ", 1000, False),
}
# Выбор одного варианта: имя → (варианты, подпись для ошибки, обязательно ли)
_SINGLE_FIELDS = {
    "years_nl": (_YEARS_NL, "сколько ты в Нидерландах", True),
    "experience": (_EXPERIENCE, "опыт", True),
    "on_camera": (_ON_CAMERA, "готовность быть в кадре", True),
    "travel": (_TRAVEL, "где готов(а) снимать", True),
    "frequency": (_FREQUENCY, "как часто хочется участвовать", True),
    "source": (_SOURCE, "откуда узнал(а) о проекте", False),
}
_MULTI_FIELDS = {"languages": _LANGUAGES, "formats": _FORMATS, "topics": _TOPICS}
_ABOUT_MIN = 20


def _label(options, code: str) -> str:
    return dict(options).get(code, "")


def _labels(options, codes) -> list[str]:
    lookup = dict(options)
    return [lookup[c] for c in codes if c in lookup]


# ---------------------------------------------------------------------------
# Разметка
# ---------------------------------------------------------------------------
def _layout(body: str, *, title: str = "Авторы podslushano.nl") -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{html.escape(title)} — podslushano.nl</title>
<style>
:root{{--bg:#f5f4f0;--card:#fff;--text:#171717;--muted:#6f6f6f;--line:#dedbd2;--field:#cfcac0;--accent:#ff5a1f;--soft:#fff1ea;--paper:#fbfaf7;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",Arial,sans-serif}}
.wrap{{width:min(760px,calc(100% - 28px));margin:0 auto;padding:30px 0 56px}}
.top{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:26px}}
.brand{{font-size:15px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}}
.version{{font-size:12px;color:var(--muted);text-align:right}}
.hero{{background:var(--card);border:1px solid var(--line);border-radius:28px;padding:30px;margin-bottom:14px}}
.eyebrow{{font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:.08em;color:var(--accent);margin:0 0 10px}}
h1{{font-size:clamp(34px,8vw,58px);line-height:.98;letter-spacing:-.045em;margin:0 0 18px}}
.lead{{font-size:19px;line-height:1.45;margin:0;color:#333;max-width:620px}}
.chips{{display:flex;flex-wrap:wrap;gap:8px;margin-top:22px}}
.chip{{padding:8px 11px;border-radius:999px;background:#f0eee8;font-size:13px;font-weight:650}}
.steps{{list-style:none;display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:0;margin:22px 0 0}}
.steps li{{background:#f0eee8;border-radius:14px;padding:10px 12px;font-size:13.5px;font-weight:700;line-height:1.3}}
.steps b{{display:block;color:var(--accent);font-size:12px;letter-spacing:.06em;text-transform:uppercase;margin-bottom:2px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:22px;padding:24px;margin:14px 0}}
h2{{font-size:23px;letter-spacing:-.02em;margin:0 0 6px;display:flex;align-items:center;gap:10px}}
.num{{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;width:30px;height:30px;border-radius:50%;background:var(--accent);color:#fff;font-size:15px;font-weight:800}}
.sub{{color:var(--muted);font-size:14.5px;line-height:1.5;margin:0 0 18px}}
h3{{font-size:17px;margin:20px 0 8px}}
p,li{{font-size:15.5px;line-height:1.58}}
p{{margin:8px 0}}
ul{{padding-left:20px;margin:8px 0}}
.note{{background:var(--soft);border-radius:16px;padding:14px 16px;margin:14px 0;font-size:14px;line-height:1.5}}
.operator{{display:grid;grid-template-columns:1fr 1fr;gap:8px 18px;font-size:14px;margin-top:10px}}
.operator div:nth-child(odd){{color:var(--muted)}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.full{{grid-column:1/-1}}
.field label,fieldset legend{{display:block;font-size:13px;font-weight:750;margin:0 0 6px;padding:0}}
.optional{{font-weight:500;color:var(--muted)}}
.hint{{font-size:12.5px;color:var(--muted);line-height:1.45;margin:-2px 0 8px}}
fieldset{{border:0;padding:0;margin:0;min-width:0}}
input:not([type=checkbox]):not([type=radio]),textarea,select{{width:100%;border:1px solid var(--field);background:#fff;color:var(--text);border-radius:14px;padding:13px 14px;font:inherit;font-size:16px;outline:none}}
textarea{{min-height:120px;resize:vertical;line-height:1.5}}
input:focus,textarea:focus,select:focus{{border-color:#999}}
.opts{{display:flex;flex-wrap:wrap;gap:8px}}
.opt{{position:relative;display:inline-flex;margin:0}}
.opt input{{position:absolute;opacity:0;width:1px;height:1px;margin:0}}
.opt span{{display:inline-flex;align-items:center;min-height:44px;padding:10px 15px;border:1px solid var(--field);border-radius:999px;background:#fff;font-size:14.5px;font-weight:600;line-height:1.25;cursor:pointer;user-select:none}}
.opt input:checked+span{{background:#171717;border-color:#171717;color:#fff}}
.opt input:focus-visible+span{{outline:2px solid var(--accent);outline-offset:2px}}
.doc{{max-height:430px;overflow:auto;border:1px solid var(--line);border-radius:16px;padding:6px 18px 14px;background:var(--paper)}}
.doc h3{{font-size:15.5px;margin:16px 0 6px}}
.doc p,.doc li{{font-size:14.5px;line-height:1.55}}
.doc:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
.doc-full{{max-height:none;overflow:visible}}
details.more{{border:1px solid var(--line);border-radius:16px;background:var(--paper);margin:14px 0}}
details.more summary{{cursor:pointer;padding:14px 18px;font-weight:750;font-size:15px}}
details.more .doc-body{{padding:0 18px 14px}}
.links{{font-size:13.5px;color:var(--muted);margin:10px 0 0}}
.check{{display:flex;gap:12px;align-items:flex-start;margin:18px 0}}
.check input{{width:22px;height:22px;margin-top:1px;flex:0 0 auto;accent-color:#171717}}
.check label{{font-weight:500;font-size:15px;line-height:1.5;margin:0}}
button{{width:100%;border:0;border-radius:16px;background:#171717;color:#fff;padding:16px 18px;font-size:16px;font-weight:800;cursor:pointer}}
button:hover{{opacity:.92}}
.error{{background:#fff0ee;color:#9d2417;border:1px solid #ffd0ca;border-radius:14px;padding:12px 14px;margin:14px 0;font-size:15px;line-height:1.45}}
.small{{font-size:12.5px;color:var(--muted);line-height:1.5}}
.hash{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all}}
a{{color:inherit}}
.ok{{font-size:58px;line-height:1;margin-bottom:12px}}
.ref{{display:inline-block;background:#f0eee8;border-radius:10px;padding:8px 10px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;margin-top:8px}}
.btn{{display:inline-block;background:#171717;color:#fff;text-decoration:none;border-radius:14px;padding:13px 18px;font-weight:800;margin-top:12px}}
@media(max-width:640px){{.hero{{padding:24px}}.card{{padding:20px}}.grid{{grid-template-columns:1fr}}.full{{grid-column:auto}}.operator{{grid-template-columns:1fr}}.operator div:nth-child(odd){{margin-top:6px}}.steps{{grid-template-columns:1fr}}.doc{{padding:4px 14px 12px}}}}
</style>
</head>
<body><main class="wrap">
<div class="top"><div class="brand">podslushano.nl</div><div class="version">Условия v{AGREEMENT_VERSION} · Неразглашение v{NDA_VERSION}</div></div>
{body}
</main></body></html>"""


def _nda_html() -> str:
    """Текст соглашения о неразглашении — из того же источника, что и хэш."""
    out: list[str] = []
    for title, paragraphs in _NDA_SECTIONS:
        out.append(f"<h3>{html.escape(title)}</h3>")
        bullets: list[str] = []
        for line in paragraphs:
            if line.startswith("• "):
                bullets.append(f"<li>{html.escape(line[2:])}</li>")
                continue
            if bullets:
                out.append("<ul>" + "".join(bullets) + "</ul>")
                bullets = []
            out.append(f"<p>{html.escape(line)}</p>")
        if bullets:
            out.append("<ul>" + "".join(bullets) + "</ul>")
    return "\n".join(out)


_TERMS_SUMMARY = """
<p><b>Это не трудоустройство и не работа по сменам.</b> Анкета подаётся в пул независимых авторов podslushano.nl и сама по себе не гарантирует место, задания или доход.</p>
<ul>
<li>нет фиксированных часов, смен и обязательного количества публикаций;</li>
<li>не нужно быть постоянно на связи;</li>
<li>можно работать, снимать и вести проекты для других;</li>
<li>любое конкретное задание можно принять или отклонить;</li>
<li>каждая платная задача и оплата за неё согласуются отдельно и заранее.</li>
</ul>
<p class="note">Юридически важна не только формулировка соглашения, но и то, как сотрудничество устроено на практике. Поэтому эти правила должны соблюдаться и в реальной работе.</p>
"""


def _terms_sections() -> str:
    return f"""
<h3>Кто решает, как работать</h3>
<p>Автор самостоятельно решает, <b>как и когда</b> снимать или готовить материал, и обычно использует свой телефон и оборудование.</p>
<p>podslushano.nl может определить <b>результат</b>: тему, что нужно передать, формат для площадки, технические требования, дедлайн и место, если без конкретной локации задача невозможна.</p>
<p>Это не означает управление рабочим днём автора: мы не устанавливаем часы, смены и способ выполнения работы.</p>

<h3>Обычный контент</h3>
<p>Автор может по собственной инициативе предлагать сторис, видео, фото, наблюдения, места и локальные истории. Делать это по графику или в определённом количестве не нужно.</p>
<p><b>Такой редакционный контент добровольный.</b> Если за конкретный материал предполагается оплата, сумма согласовывается заранее.</p>

<h3>Платные задания</h3>
<p>Каждая коммерческая съёмка или другая оплачиваемая задача предлагается <b>отдельно</b>.</p>
<p>До того как автор согласится, фиксируем минимум:</p>
<ul>
<li>что должно получиться в итоге;</li>
<li>какие материалы нужно передать;</li>
<li>дедлайн;</li>
<li><b>оплату автору.</b></li>
</ul>
<p>Можно отказаться от любой такой задачи. Отказ не закрывает возможность участвовать в проекте или предлагать свой контент.</p>
<p class="note">Способ оплаты зависит от статуса автора. Перед первой выплатой podslushano.nl может запросить данные для счёта, KVK/BTW или другую информацию, необходимую для корректной оплаты, бухгалтерии и обязательной отчётности.</p>

<h3>Билеты и приглашения</h3>
<p>podslushano.nl может предлагать билеты, приглашения и аккредитации на концерты, фестивали, открытия и другие события.</p>
<p>Если в обмен ожидается материал, <b>что именно нужно снять или передать согласовывается до того, как автор принимает приглашение.</b> Билеты и приглашения не гарантируются и не являются постоянной зарплатой.</p>

<h3>Что остаётся за podslushano.nl</h3>
<p>podslushano.nl решает, публиковать ли присланный материал, на какой площадке, как его оформить или отредактировать, а также ведёт переговоры с рекламодателями, определяет цены, рекламные условия, стандарты бренда и уровни доступа.</p>
<p><b>Основатель и главный редактор — {_OPERATOR_NAME}.</b> Финальные редакционные и коммерческие решения по проекту остаются за ним.</p>

<h3>Конфиденциальность</h3>
<p>Всё непубличное, что автор узнаёт внутри проекта, остаётся внутри команды. Подробно это описано в отдельном <a href="/authors/nda">соглашении о неразглашении</a> v{NDA_VERSION}, которое принимается вместе с этими условиями.</p>
<p>Непубличную коммерческую и операционную информацию нельзя разглашать ещё 24 месяца после прекращения сотрудничества, а личность анонимных отправителей и персональные данные участников сообщества — бессрочно.</p>

<h3>Клиенты и собственные проекты</h3>
<p>Автор может вести свой блог, развивать личный бренд, работать с другими заказчиками и самостоятельно зарабатывать.</p>
<p>При этом рекламодателя или партнёра, с которым автор познакомился именно через podslushano.nl, нельзя сознательно уводить из проекта и заключать с ним напрямую аналогичную рекламную сделку в обход podslushano.nl без письменного разрешения в течение 12 месяцев после последней совместной работы с этим контактом.</p>
<p>Это ограничение не касается отношений, которые у автора существовали до знакомства через podslushano.nl.</p>

<h3>Контент и права</h3>
<p>Автор подтверждает, что имеет право передавать присланные фото, видео и тексты.</p>
<p>Передавая материал специально для podslushano.nl, автор предоставляет проекту неисключительное право редактировать, оформлять, публиковать, повторно размещать и хранить этот материал в каналах podslushano.nl и материалах о самом проекте.</p>
<p>Для платной рекламной задачи дополнительное использование материала рекламодателем действует в рамках условий конкретной кампании.</p>

<h3>Доступы и представление проекта</h3>
<p>Доступы выдаются только по необходимости и могут быть изменены или отозваны. Пароли, master/admin-доступы, CRM, полная клиентская база и финансовая информация автоматически авторам не предоставляются.</p>
<p>Действующий автор может называть себя автором podslushano.nl, но не может от имени проекта назначать цены, заключать коммерческие договорённости или представляться владельцем/уполномоченным коммерческим представителем без отдельного разрешения.</p>

<h3>Если сотрудничество заканчивается</h3>
<p>Любая сторона может прекратить участие в любой момент. Уже принятые оплачиваемые задачи закрываются по согласованным условиям либо стороны отдельно договариваются об их прекращении.</p>
<p>После выхода выданные доступы могут быть отозваны сразу, а непубличные материалы и внутренние данные нельзя использовать дальше.</p>

<h3>Персональные данные и право</h3>
<p>Для обработки заявки и фиксации принятия документов мы сохраняем данные и ответы из анкеты, версии и контрольные хэши этих условий и соглашения о неразглашении, дату принятия и технические данные user-agent. Финансовые и налоговые данные могут храниться, когда это требуется законом.</p>
<p>Запросить доступ к своим данным, исправить или удалить их можно по адресу <a href="mailto:{_EMAIL}">{_EMAIL}</a>, если закон не обязывает нас их хранить.</p>
<p>Применяется право Нидерландов. Обязательные нормы закона имеют приоритет над формулировками этого соглашения. Сначала стороны стараются решить спор напрямую; при невозможности — спор рассматривается компетентным судом Нидерландов.</p>
<p class="small">Политика конфиденциальности сайта: <a href="https://www.podslushano.nl/privacy-statement-eu/" target="_blank" rel="noopener">podslushano.nl/privacy-statement-eu/</a></p>
"""


def _operator_html() -> str:
    return f"""<div class="operator">
<div>Оператор</div><div><b>{_OPERATOR_NAME}</b></div>
<div>Проект</div><div>podslushano.nl</div>
<div>KVK</div><div>{_KVK}</div>
<div>BTW</div><div>{_BTW}</div>
<div>Адрес</div><div>{_ADDRESS}</div>
<div>E-mail</div><div><a href="mailto:{_EMAIL}">{_EMAIL}</a></div>
<div>Сайт</div><div><a href="{_SITE}" target="_blank" rel="noopener">podslushano.nl</a></div>
</div>"""


def _optional_mark(required: bool) -> str:
    return "" if required else ' <span class="optional">(по желанию)</span>'


def _text_field(name: str, label: str, values: dict, *, kind: str = "text", placeholder: str = "",
                autocomplete: str = "", hint: str = "", full: bool = False) -> str:
    _, maxlength, required = _TEXT_FIELDS[name]
    value = html.escape(str(values.get(name) or ""), quote=True)
    attrs = f' maxlength="{maxlength}"' + (" required" if required else "")
    if placeholder:
        attrs += f' placeholder="{html.escape(placeholder, quote=True)}"'
    if autocomplete:
        attrs += f' autocomplete="{autocomplete}"'
    hint_html = f'<p class="hint">{hint}</p>' if hint else ""
    if kind == "textarea":
        control = f'<textarea id="f-{name}" name="{name}"{attrs}>{value}</textarea>'
    else:
        control = f'<input id="f-{name}" type="{kind}" name="{name}" value="{value}"{attrs}>'
    css = "field full" if full else "field"
    return (f'<div class="{css}"><label for="f-{name}">{label}{_optional_mark(required)}</label>'
            f'{hint_html}{control}</div>')


def _choice_group(name: str, legend: str, options, values: dict, *, multiple: bool,
                  required: bool, hint: str = "") -> str:
    selected = values.get(name)
    chosen = set(selected or []) if multiple else {selected}
    kind = "checkbox" if multiple else "radio"
    # Для радиокнопок браузер сам проверит, что выбран один вариант; для галочек «хотя бы одна» — сервер
    req = " required" if required and not multiple else ""
    items = "".join(
        f'<label class="opt"><input type="{kind}" name="{name}" value="{code}"'
        f'{" checked" if code in chosen else ""}{req}><span>{html.escape(label)}</span></label>'
        for code, label in options
    )
    hint_html = f'<p class="hint">{hint}</p>' if hint else ""
    return (f'<fieldset class="field full"><legend>{legend}{_optional_mark(required)}</legend>'
            f'{hint_html}<div class="opts">{items}</div></fieldset>')


def _select_field(name: str, label: str, options, values: dict) -> str:
    current = values.get(name) or ""
    opts = '<option value="">— выбрать —</option>' + "".join(
        f'<option value="{code}"{" selected" if code == current else ""}>{html.escape(text)}</option>'
        for code, text in options
    )
    required = _SINGLE_FIELDS[name][2]
    return (f'<div class="field"><label for="f-{name}">{label}{_optional_mark(required)}</label>'
            f'<select id="f-{name}" name="{name}">{opts}</select></div>')


def _form_page(error: str = "", values: dict | None = None) -> str:
    values = values or {}
    error_html = f'<div class="error" role="alert">{html.escape(error)}</div>' if error else ""
    body = f"""
<section class="hero">
<p class="eyebrow">Авторы podslushano.nl</p>
<h1>Стать автором</h1>
<p class="lead">Расскажи о себе, прими соглашение о неразглашении и условия участия — это займёт 5–7 минут. Мы прочитаем анкету и напишем тебе в Telegram.</p>
<div class="chips"><span class="chip">без графика</span><span class="chip">можно отказаться</span><span class="chip">каждая платная задача отдельно</span></div>
<ol class="steps">
<li><b>Шаг 1</b>Анкета о себе</li>
<li><b>Шаг 2</b>Неразглашение</li>
<li><b>Шаг 3</b>Условия участия</li>
</ol>
</section>
{error_html}
<form method="post" action="/authors/agreement">

<section class="card">
<h2><span class="num">1</span>Контакты</h2>
<p class="sub">Чтобы мы могли связаться с тобой и понимать, в каком ты городе.</p>
<div class="grid">
{_text_field("full_name", "ФИО полностью", values, autocomplete="name", full=True)}
{_text_field("city", "Город в Нидерландах", values, autocomplete="address-level2")}
{_text_field("email", "E-mail", values, kind="email", autocomplete="email")}
{_text_field("telegram", "Telegram", values, placeholder="@username или ссылка")}
{_text_field("instagram", "Instagram", values, placeholder="@username или ссылка")}
</div>
</section>

<section class="card">
<h2><span class="num">1</span>О тебе</h2>
<p class="sub">Нет правильных ответов — нам важно понять, кто ты и что тебе интересно.</p>
<div class="grid">
{_choice_group("years_nl", "Сколько ты живёшь в Нидерландах?", _YEARS_NL, values, multiple=False, required=True)}
{_text_field("occupation", "Чем занимаешься?", values, placeholder="Работа, учёба, своё дело…", full=True)}
{_choice_group("languages", "На каких языках свободно говоришь?", _LANGUAGES, values, multiple=True, required=False)}
{_text_field("about", "Расскажи о себе", values, kind="textarea", full=True,
             hint="Пара предложений: кто ты, чем увлекаешься, почему хочешь стать автором podslushano.nl.")}
</div>
</section>

<section class="card">
<h2><span class="num">1</span>Что хочешь делать</h2>
<p class="sub">Можно выбрать несколько вариантов.</p>
<div class="grid">
{_choice_group("formats", "Какие форматы тебе интересны?", _FORMATS, values, multiple=True, required=True,
               hint="Выбери хотя бы один.")}
{_choice_group("topics", "О чём хочется рассказывать?", _TOPICS, values, multiple=True, required=False)}
{_choice_group("experience", "Есть ли опыт создания контента?", _EXPERIENCE, values, multiple=False, required=True)}
{_text_field("portfolio", "Примеры работ", values, kind="textarea", full=True,
             placeholder="Ссылки на посты, видео, статьи или аккаунты",
             hint="Если опыта пока нет — оставь пустым, это не помешает.")}
{_text_field("phone_model", "На какой телефон снимаешь?", values, placeholder="Например: iPhone 15 Pro", full=True)}
{_choice_group("on_camera", "Готов(а) появляться в кадре?", _ON_CAMERA, values, multiple=False, required=True)}
{_choice_group("travel", "Где готов(а) снимать?", _TRAVEL, values, multiple=False, required=True)}
{_choice_group("frequency", "Как часто примерно хочется участвовать?", _FREQUENCY, values, multiple=False,
               required=True, hint="Это ориентир для нас, а не обязательство: графика и норм нет.")}
{_select_field("source", "Откуда узнал(а) о podslushano.nl?", _SOURCE, values)}
</div>
</section>

<section class="card">
<h2><span class="num">2</span>Соглашение о неразглашении</h2>
<p class="sub">В команде авторов ты увидишь то, чего не видят подписчики: неопубликованные истории, закрытые чаты, данные людей, которые пишут нам анонимно, условия рекламодателей. Всё это остаётся внутри команды.</p>
<div class="doc" tabindex="0" role="region" aria-label="Текст соглашения о неразглашении">
<p class="small">{NDA_TITLE} · версия {NDA_VERSION} от {NDA_DATE}</p>
{_nda_html()}
</div>
<p class="links"><a href="/authors/nda" target="_blank" rel="noopener">Открыть соглашение отдельной страницей</a></p>
<div class="check"><input type="checkbox" id="nda" name="nda" value="1" required><label for="nda">Я прочитал(а) и принимаю соглашение о неразглашении podslushano.nl, версия {NDA_VERSION} от {NDA_DATE}. Я не буду разглашать конфиденциальную информацию, которую узнаю в сообществе авторов, и никогда не раскрою личность анонимных отправителей.</label></div>
</section>

<section class="card">
<h2><span class="num">3</span>Условия участия</h2>
<p class="sub">Как устроено сотрудничество: что добровольно, как работают платные задания и что остаётся за редакцией.</p>
{_TERMS_SUMMARY}
<details class="more">
<summary>Полный текст условий v{AGREEMENT_VERSION}</summary>
<div class="doc-body">{_terms_sections()}</div>
</details>
<h3>Кто стоит за проектом</h3>
{_operator_html()}
<div class="check"><input type="checkbox" id="adult" name="adult" value="1" required><label for="adult">Мне 18 лет или больше.</label></div>
<div class="check"><input type="checkbox" id="accept" name="accept" value="1" required><label for="accept">Я прочитал(а) и принимаю условия независимого участия в podslushano.nl, версия {AGREEMENT_VERSION} от {AGREEMENT_DATE}, включая правила платных заданий, конфиденциальности и работы с клиентами. Я понимаю, что отправка анкеты не означает автоматическое принятие в пул авторов и не создаёт гарантии заданий или дохода.</label></div>
<button type="submit">Принять условия и отправить анкету</button>
<p class="small">После отправки система зафиксирует дату, версии и контрольные хэши принятых документов. Условия: <span class="hash">{AGREEMENT_SHA256[:12]}…</span> · Неразглашение: <span class="hash">{NDA_SHA256[:12]}…</span></p>
</section>
</form>
"""
    return _layout(body)


def _nda_page() -> str:
    body = f"""
<section class="hero">
<p class="eyebrow">Авторы podslushano.nl</p>
<h1>Соглашение о неразглашении</h1>
<p class="lead">Версия {NDA_VERSION} от {NDA_DATE}. Принимается вместе с анкетой автора.</p>
<a class="btn" href="/authors/agreement">Заполнить анкету</a>
</section>
<section class="card">
<div class="doc doc-full">{_nda_html()}</div>
<p class="small">SHA-256: <span class="hash">{NDA_SHA256}</span></p>
</section>
"""
    return _layout(body, title="Соглашение о неразглашении")


def _terms_page() -> str:
    body = f"""
<section class="hero">
<p class="eyebrow">Авторы podslushano.nl</p>
<h1>Условия участия</h1>
<p class="lead">Версия {AGREEMENT_VERSION} от {AGREEMENT_DATE}. Принимаются вместе с анкетой автора.</p>
<a class="btn" href="/authors/agreement">Заполнить анкету</a>
</section>
<section class="card">
<h2>Сначала главное</h2>
{_TERMS_SUMMARY}
{_terms_sections()}
<h3>Кто стоит за проектом</h3>
{_operator_html()}
<p class="small">SHA-256: <span class="hash">{AGREEMENT_SHA256}</span></p>
</section>
"""
    return _layout(body, title="Условия участия")


def _success_page(record_id: int, full_name: str) -> str:
    ref = f"PNL-AUTHOR-{record_id:05d}"
    body = f"""
<section class="hero">
<div class="ok">✓</div>
<p class="eyebrow">Готово</p>
<h1>Анкета получена</h1>
<p class="lead"><b>{html.escape(full_name)}</b>, спасибо! Анкета у нас, а принятие условий участия v{AGREEMENT_VERSION} и соглашения о неразглашении v{NDA_VERSION} зафиксировано.</p>
<div class="ref">{ref}</div>
</section>
<section class="card">
<h2>Что дальше</h2>
<p>Алекс прочитает анкету, напишет тебе в Telegram и, если всё сложится, добавит в закрытый чат авторов и расскажет про ближайшие идеи, события и съёмки.</p>
<p>Документы, которые ты принял(а), можно открыть и сохранить: <a href="/authors/nda">соглашение о неразглашении</a> · <a href="/authors/terms">условия участия</a>.</p>
<p class="small">Условия v{AGREEMENT_VERSION} ({AGREEMENT_DATE}) · SHA-256: <span class="hash">{AGREEMENT_SHA256}</span></p>
<p class="small">Неразглашение v{NDA_VERSION} ({NDA_DATE}) · SHA-256: <span class="hash">{NDA_SHA256}</span></p>
</section>
"""
    return _layout(body, title="Анкета получена")


# ---------------------------------------------------------------------------
# Обработка формы
# ---------------------------------------------------------------------------
def _parse_form(data) -> tuple[dict, str]:
    """Возвращает (значения для повторного показа формы, текст ошибки или "")."""
    def text(name: str) -> str:
        return str(data.get(name) or "").strip()

    def many(name: str, options) -> list[str]:
        got = set(data.getall(name, [])) if hasattr(data, "getall") else set()
        return [code for code, _ in options if code in got]   # порядок как на странице, без дублей и мусора

    values: dict = {name: text(name) for name in _TEXT_FIELDS}
    values["email"] = values["email"].lower()
    for name in _SINGLE_FIELDS:
        values[name] = text(name)
    for name, options in _MULTI_FIELDS.items():
        values[name] = many(name, options)

    missing = [label for name, (label, _, required) in _TEXT_FIELDS.items() if required and not values[name]]
    missing += [label for name, (_, label, required) in _SINGLE_FIELDS.items() if required and not values[name]]
    if missing:
        return values, "Не заполнено: " + ", ".join(missing) + "."
    too_long = [label for name, (label, maxlength, _) in _TEXT_FIELDS.items() if len(values[name]) > maxlength]
    if too_long:
        return values, "Слишком длинный ответ: " + ", ".join(too_long) + "."
    if not _EMAIL_RE.match(values["email"]):
        return values, "Укажи корректный e-mail."
    for name, (options, label, _) in _SINGLE_FIELDS.items():
        if values[name] and not _label(options, values[name]):
            return values, f"Выбери вариант из списка: {label}."
    if not values["formats"]:
        return values, "Выбери хотя бы один формат, который тебе интересен."
    if len(values["about"]) < _ABOUT_MIN:
        return values, "Расскажи о себе чуть подробнее — хотя бы пару предложений."
    if data.get("adult") != "1":
        return values, "Участие доступно только с 18 лет."
    if data.get("nda") != "1":
        return values, "Нужно принять соглашение о неразглашении."
    if data.get("accept") != "1":
        return values, "Нужно принять условия участия."
    return values, ""


def _questionnaire(values: dict) -> dict:
    """Ответы анкеты подписями, которые видел человек (для базы и уведомления)."""
    return {
        "years_in_nl": _label(_YEARS_NL, values["years_nl"]),
        "occupation": values["occupation"],
        "languages": _labels(_LANGUAGES, values["languages"]),
        "about": values["about"],
        "formats": _labels(_FORMATS, values["formats"]),
        "topics": _labels(_TOPICS, values["topics"]),
        "experience": _label(_EXPERIENCE, values["experience"]),
        "portfolio": values["portfolio"],
        "on_camera": _label(_ON_CAMERA, values["on_camera"]),
        "travel": _label(_TRAVEL, values["travel"]),
        "frequency": _label(_FREQUENCY, values["frequency"]),
        "source": _label(_SOURCE, values["source"]),
    }


def _clip(value: str, limit: int) -> str:
    value = value.strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _admin_message(values: dict, answers: dict, record_id: int) -> str:
    def e(value: str) -> str:
        return html.escape(value or "—")

    def joined(items: list[str]) -> str:
        return html.escape(", ".join(items)) if items else "—"

    lines = [
        "📝 <b>Новая анкета автора</b>",
        "",
        f"ФИО: {e(values['full_name'])}",
        f"Город: {e(values['city'])} · в НЛ: {e(answers['years_in_nl'])}",
        f"Telegram: {e(values['telegram'])}",
        f"Instagram: {e(values['instagram'])}",
        f"E-mail: {e(values['email'])}",
        f"Занятие: {e(answers['occupation'])}",
        f"Языки: {joined(answers['languages'])}",
        "",
        f"Форматы: {joined(answers['formats'])}",
        f"Темы: {joined(answers['topics'])}",
        f"Опыт: {e(answers['experience'])}",
        f"Телефон: {e(values['phone_model'])}",
        f"В кадре: {e(answers['on_camera'])}",
        f"Где снимать: {e(answers['travel'])}",
        f"Как часто: {e(answers['frequency'])}",
        f"Откуда узнал(а): {e(answers['source'])}",
        "",
        "<b>О себе</b>",
        e(_clip(answers["about"], 1200)),
    ]
    if answers["portfolio"]:
        lines += ["", "<b>Примеры работ</b>", e(_clip(answers["portfolio"], 500))]
    lines += ["", f"Условия v{AGREEMENT_VERSION} · Неразглашение v{NDA_VERSION} · PNL-AUTHOR-{record_id:05d}"]
    return "\n".join(lines)


def _html_response(text: str, status: int = 200) -> web.Response:
    return web.Response(
        text=text, status=status, content_type="text/html",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def agreement_page(request: web.Request) -> web.Response:
    return _html_response(_form_page())


async def nda_page(request: web.Request) -> web.Response:
    return _html_response(_nda_page())


async def terms_page(request: web.Request) -> web.Response:
    return _html_response(_terms_page())


async def agreement_submit(request: web.Request) -> web.Response:
    data = await request.post()
    values, error = _parse_form(data)
    if error:
        return _html_response(_form_page(error, values), status=400)
    answers = _questionnaire(values)

    async with get_session() as session:
        existing = await session.scalar(
            select(AuthorAgreementAcceptance).where(
                func.lower(AuthorAgreementAcceptance.email) == values["email"],
                AuthorAgreementAcceptance.agreement_version == AGREEMENT_VERSION,
            )
        )
        if existing is not None:
            return _html_response(_success_page(existing.id, existing.full_name))

        record = AuthorAgreementAcceptance(
            full_name=values["full_name"],
            city=values["city"],
            email=values["email"],
            telegram=values["telegram"],
            instagram=values["instagram"] or None,
            phone_model=values["phone_model"],
            questionnaire=json.dumps(answers, ensure_ascii=False),
            agreement_version=AGREEMENT_VERSION,
            agreement_sha256=AGREEMENT_SHA256,
            nda_version=NDA_VERSION,
            nda_sha256=NDA_SHA256,
            user_agent=(request.headers.get("User-Agent") or "")[:500] or None,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        record_id = record.id

    bot = request.app.get("bot")
    if bot is not None:
        msg = _admin_message(values, answers, record_id)
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_message(admin_id, msg)
            except Exception as exc:  # noqa: BLE001
                log.warning("Не уведомил админа о новом авторе: %s", exc)

    return _html_response(_success_page(record_id, values["full_name"]))


async def agreement_short(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound(location="/authors/agreement")


def install_routes(app: web.Application) -> None:
    app.router.add_get("/authors", agreement_short)
    app.router.add_get("/authors/agreement", agreement_page)
    app.router.add_post("/authors/agreement", agreement_submit)
    app.router.add_get("/authors/nda", nda_page)
    app.router.add_get("/authors/terms", terms_page)
