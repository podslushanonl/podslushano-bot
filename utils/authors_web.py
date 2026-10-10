"""Public author agreement page for the Podslushano.nl contributor network."""
from __future__ import annotations

import hashlib
import html
import logging
import re

from aiohttp import web
from sqlalchemy import func, select

import config
from database.db import get_session
from database.models import AuthorAgreementAcceptance

log = logging.getLogger(__name__)

AGREEMENT_VERSION = "1.1"
AGREEMENT_DATE = "10.10.2026"
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

_OPERATOR_NAME = "Aleksei Maksimovich Egorov"
_KVK = "98882317"
_BTW = "NL005359099B74"
_ADDRESS = "Karel Doormanstraat 63, 5342 TJ Oss, Nederland"
_EMAIL = "podslushano.nl@gmail.com"
_SITE = "https://www.podslushano.nl"

_AGREEMENT_CANONICAL = f"""
Podslushano.nl Independent Contributor Terms v{AGREEMENT_VERSION} dated {AGREEMENT_DATE}.
Operator: {_OPERATOR_NAME}; KVK {_KVK}; BTW {_BTW}; {_ADDRESS}; {_EMAIL}.

1. Application and scope.
Submitting the form records acceptance of these terms. It does not automatically admit the applicant to
the author pool, create employment, guarantee assignments, compensation or income. If Podslushano.nl
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
their own phone/equipment. Podslushano.nl may define the intended result: subject, deliverables, platform,
technical or brand requirements, deadline and a location where the nature of the assignment requires it.
Podslushano.nl does not direct the contributor's day-to-day working method, hours or work process.

4. Voluntary editorial content.
Stories, video, photos, observations and local reports proposed by the contributor are voluntary. There
is no required publication frequency. Organic/editorial content is unpaid unless payment is expressly
agreed before the work is accepted.

5. Events and invitations.
Podslushano.nl may offer tickets, invitations, accreditation or access to events. Availability is not
guaranteed. A ticket or invitation is primarily access needed for the event and is not a recurring wage.
If Podslushano.nl expects content in return, the expected result is agreed before the contributor accepts.

6. Paid assignments.
Each commercial or otherwise paid task is offered separately. Before acceptance, the parties agree at
least the intended result/deliverables, deadline and contributor fee. The contributor may accept or refuse
without affecting their ability to propose voluntary content. There is no guarantee of recurring paid work.
Before the first payment, Podslushano.nl may request invoice, KVK/BTW or other information required for
lawful payment, bookkeeping or reporting, depending on the contributor's status.

7. Editorial and commercial control.
Podslushano.nl decides whether submitted content is published, where it is published, how it is edited or
formatted, and manages advertiser negotiations, prices, campaigns, brand standards and access permissions.
This control concerns the publication/result and Podslushano.nl business decisions, not supervision of the
contributor's independent work process.

8. Confidentiality.
Internal chat content, advertiser and partner contacts obtained through the project, pricing, discounts,
commercial terms, analytics, unpublished plans, workflows, access credentials and internal feedback are
confidential. They may not be shared outside the team without permission. This duty continues for 24 months
after cooperation ends for non-public commercial and operational information.

9. Non-circumvention.
For 12 months after the contributor's last work with a specific advertiser or partner first introduced
through Podslushano.nl, the contributor will not knowingly bypass Podslushano.nl to solicit or contract
directly with that contact for substantially similar advertising services without written permission.
This does not apply to relationships demonstrably existing before the introduction by Podslushano.nl.

10. Own projects.
The contributor may run personal social media, build a personal brand, work for others and earn independently,
provided they do not misuse Podslushano.nl confidential information, access, brand assets or project-originated
commercial relationships.

11. Content rights.
The contributor confirms they have the right to submit the content. By submitting content specifically for
Podslushano.nl, the contributor grants Podslushano.nl a non-exclusive, worldwide, royalty-free licence to edit,
format, publish, repost and archive that content across Podslushano.nl channels and materials promoting the
project. Content created for a paid campaign may also be used by the relevant advertiser within the campaign
scope agreed for that assignment.

12. Access and representation.
Access is role-based and may be changed or withdrawn at any time. Passwords, master/admin access, CRM, full
client lists and financial information are not automatically provided. The contributor may describe themselves
as a Podslushano.nl author while actively participating, but may not bind Podslushano.nl, quote commercial prices
or present themselves as owner or authorized commercial representative unless explicitly authorized.

13. Ending cooperation.
Either side may stop the contributor relationship at any time. Accepted paid assignments are completed or
closed by mutual agreement. Project access may be revoked immediately when cooperation ends. Unpublished
confidential materials and access data must not be retained or used after exit.

14. Data and law.
Podslushano.nl stores the applicant's name, city, email, Telegram, optional Instagram, phone model, agreement
version/hash, acceptance timestamp and technical user-agent data for application administration and evidence
of acceptance. Financial and tax data may be retained where legally required. Dutch law applies. The parties
first try to resolve disputes informally; if that fails, the competent court in the Netherlands has jurisdiction,
subject to mandatory law.
""".strip()

AGREEMENT_SHA256 = hashlib.sha256(_AGREEMENT_CANONICAL.encode("utf-8")).hexdigest()


def _layout(body: str, *, title: str = "Авторы Podslushano.nl") -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{html.escape(title)} — Podslushano.nl</title>
<style>
:root{{--bg:#f5f4f0;--card:#fff;--text:#171717;--muted:#6f6f6f;--line:#dedbd2;--accent:#ff5a1f;--soft:#fff1ea;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",Arial,sans-serif}}
.wrap{{width:min(760px,calc(100% - 28px));margin:0 auto;padding:30px 0 56px}}
.top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:26px}}
.brand{{font-size:15px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}}
.version{{font-size:12px;color:var(--muted)}}
.hero{{background:var(--card);border:1px solid var(--line);border-radius:28px;padding:30px;margin-bottom:14px}}
.eyebrow{{font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:.08em;color:var(--accent);margin:0 0 10px}}
h1{{font-size:clamp(34px,8vw,58px);line-height:.98;letter-spacing:-.045em;margin:0 0 18px}}
.lead{{font-size:19px;line-height:1.45;margin:0;color:#333;max-width:620px}}
.chips{{display:flex;flex-wrap:wrap;gap:8px;margin-top:22px}}
.chip{{padding:8px 11px;border-radius:999px;background:#f0eee8;font-size:13px;font-weight:650}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:22px;padding:24px;margin:14px 0}}
h2{{font-size:23px;letter-spacing:-.02em;margin:0 0 13px}}
h3{{font-size:17px;margin:20px 0 8px}}
p,li{{font-size:15.5px;line-height:1.58}}
p{{margin:8px 0}}
ul{{padding-left:20px;margin:8px 0}}
.note{{background:var(--soft);border-radius:16px;padding:14px 16px;margin:14px 0;font-size:14px;line-height:1.5}}
.operator{{display:grid;grid-template-columns:1fr 1fr;gap:8px 18px;font-size:14px}}
.operator div:nth-child(odd){{color:var(--muted)}}
form{{margin-top:8px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
label{{display:block;font-size:13px;font-weight:750;margin:0 0 6px}}
input{{width:100%;border:1px solid #cfcac0;background:#fff;border-radius:14px;padding:13px 14px;font:inherit;outline:none}}
input:focus{{border-color:#999}}
.full{{grid-column:1/-1}}
.check{{display:flex;gap:10px;align-items:flex-start;margin:18px 0}}
.check input{{width:20px;height:20px;margin-top:2px;flex:0 0 auto}}
.check label{{font-weight:500;line-height:1.45;margin:0}}
button{{width:100%;border:0;border-radius:16px;background:#171717;color:#fff;padding:15px 18px;font-size:16px;font-weight:800;cursor:pointer}}
button:hover{{opacity:.92}}
.error{{background:#fff0ee;color:#9d2417;border:1px solid #ffd0ca;border-radius:14px;padding:12px 14px;margin-bottom:14px}}
.small{{font-size:12.5px;color:var(--muted);line-height:1.5}}
a{{color:inherit}}
.ok{{font-size:58px;line-height:1;margin-bottom:12px}}
.ref{{display:inline-block;background:#f0eee8;border-radius:10px;padding:8px 10px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;margin-top:8px}}
@media(max-width:640px){{.hero{{padding:24px}}.card{{padding:20px}}.grid{{grid-template-columns:1fr}}.full{{grid-column:auto}}.operator{{grid-template-columns:1fr}}.operator div:nth-child(odd){{margin-top:6px}}}}
</style>
</head>
<body><main class="wrap">
<div class="top"><div class="brand">Podslushano.nl</div><div class="version">Условия v{AGREEMENT_VERSION} · {AGREEMENT_DATE}</div></div>
{body}
</main></body></html>"""


def _terms_sections() -> str:
    return """
<section class="card">
<h2>Сначала главное</h2>
<p><b>Это не трудоустройство и не работа по сменам.</b> Анкета подаётся в пул независимых авторов Podslushano.nl и сама по себе не гарантирует место, задания или доход.</p>
<ul>
<li>нет фиксированных часов, смен и обязательного количества публикаций;</li>
<li>не нужно быть постоянно на связи;</li>
<li>можно работать, снимать и вести проекты для других;</li>
<li>любое конкретное задание можно принять или отклонить.</li>
</ul>
<p class="note">Юридически важна не только формулировка соглашения, но и то, как сотрудничество устроено на практике. Поэтому эти правила должны соблюдаться и в реальной работе.</p>
</section>

<section class="card">
<h2>Кто решает, как работать</h2>
<p>Автор самостоятельно решает, <b>как и когда</b> снимать или готовить материал, и обычно использует свой телефон и оборудование.</p>
<p>Podslushano.nl может определить <b>результат</b>: тему, что нужно передать, формат для площадки, технические требования, дедлайн и место, если без конкретной локации задача невозможна.</p>
<p>Это не означает управление рабочим днём автора: мы не устанавливаем часы, смены и способ выполнения работы.</p>
</section>

<section class="card">
<h2>Обычный контент</h2>
<p>Автор может по собственной инициативе предлагать сторис, видео, фото, наблюдения, места и локальные истории. Делать это по графику или в определённом количестве не нужно.</p>
<p><b>Такой редакционный контент добровольный.</b> Если за конкретный материал предполагается оплата, сумма согласовывается заранее.</p>
</section>

<section class="card">
<h2>Платные задания</h2>
<p>Каждая коммерческая съёмка или другая оплачиваемая задача предлагается <b>отдельно</b>.</p>
<p>До того как автор согласится, фиксируем минимум:</p>
<ul>
<li>что должно получиться в итоге;</li>
<li>какие материалы нужно передать;</li>
<li>дедлайн;</li>
<li><b>оплату автору.</b></li>
</ul>
<p>Можно отказаться от любой такой задачи. Отказ не закрывает возможность участвовать в проекте или предлагать свой контент.</p>
<p class="note">Способ оплаты зависит от статуса автора. Перед первой выплатой Podslushano.nl может запросить данные для счёта, KVK/BTW или другую информацию, необходимую для корректной оплаты, бухгалтерии и обязательной отчётности.</p>
</section>

<section class="card">
<h2>Билеты и приглашения</h2>
<p>Podslushano.nl может предлагать билеты, приглашения и аккредитации на концерты, фестивали, открытия и другие события.</p>
<p>Если в обмен ожидается материал, <b>что именно нужно снять или передать согласовывается до того, как автор принимает приглашение.</b> Билеты и приглашения не гарантируются и не являются постоянной зарплатой.</p>
</section>

<section class="card">
<h2>Что остаётся за Podslushano.nl</h2>
<p>Podslushano.nl решает, публиковать ли присланный материал, на какой площадке, как его оформить или отредактировать, а также ведёт переговоры с рекламодателями, определяет цены, рекламные условия, стандарты бренда и уровни доступа.</p>
<p><b>Основатель и главный редактор — Aleksei Maksimovich Egorov.</b> Финальные редакционные и коммерческие решения по проекту остаются за ним.</p>
</section>

<section class="card">
<h2>Конфиденциальность</h2>
<p>Без разрешения нельзя передавать вне команды:</p>
<ul>
<li>содержимое внутреннего чата и неопубликованные планы;</li>
<li>контакты рекламодателей и партнёров, полученные через проект;</li>
<li>цены, скидки, коммерческие условия, аналитику и внутренние процессы;</li>
<li>пароли, токены, служебные ссылки и другие доступы;</li>
<li>внутреннюю редакционную обратную связь.</li>
</ul>
<p>Обязанность не разглашать непубличную коммерческую и операционную информацию действует ещё 24 месяца после прекращения сотрудничества.</p>
</section>

<section class="card">
<h2>Клиенты и собственные проекты</h2>
<p>Автор может вести свой блог, развивать личный бренд, работать с другими заказчиками и самостоятельно зарабатывать.</p>
<p>При этом рекламодателя или партнёра, с которым автор познакомился именно через Podslushano.nl, нельзя сознательно уводить из проекта и заключать с ним напрямую аналогичную рекламную сделку в обход Podslushano.nl без письменного разрешения в течение 12 месяцев после последней совместной работы с этим контактом.</p>
<p>Это ограничение не касается отношений, которые у автора существовали до знакомства через Podslushano.nl.</p>
</section>

<section class="card">
<h2>Контент и права</h2>
<p>Автор подтверждает, что имеет право передавать присланные фото, видео и тексты.</p>
<p>Передавая материал специально для Podslushano.nl, автор предоставляет проекту неисключительное право редактировать, оформлять, публиковать, повторно размещать и хранить этот материал в каналах Podslushano.nl и материалах о самом проекте.</p>
<p>Для платной рекламной задачи дополнительное использование материала рекламодателем действует в рамках условий конкретной кампании.</p>
</section>

<section class="card">
<h2>Доступы и представление проекта</h2>
<p>Доступы выдаются только по необходимости и могут быть изменены или отозваны. Пароли, master/admin-доступы, CRM, полная клиентская база и финансовая информация автоматически авторам не предоставляются.</p>
<p>Действующий автор может называть себя автором Podslushano.nl, но не может от имени проекта назначать цены, заключать коммерческие договорённости или представляться владельцем/уполномоченным коммерческим представителем без отдельного разрешения.</p>
</section>

<section class="card">
<h2>Если сотрудничество заканчивается</h2>
<p>Любая сторона может прекратить участие в любой момент. Уже принятые оплачиваемые задачи закрываются по согласованным условиям либо стороны отдельно договариваются об их прекращении.</p>
<p>После выхода выданные доступы могут быть отозваны сразу, а непубличные материалы и внутренние данные нельзя использовать дальше.</p>
</section>

<section class="card">
<h2>Персональные данные и право</h2>
<p>Для обработки заявки и фиксации принятия условий мы сохраняем данные из формы, версию и контрольный хэш условий, дату принятия и технические данные user-agent. Финансовые и налоговые данные могут храниться, когда это требуется законом.</p>
<p>Применяется право Нидерландов. Обязательные нормы закона имеют приоритет над формулировками этого соглашения. Сначала стороны стараются решить спор напрямую; при невозможности — спор рассматривается компетентным судом Нидерландов.</p>
<p class="small">Политика конфиденциальности сайта: <a href="https://www.podslushano.nl/privacy-statement-eu/" target="_blank" rel="noopener">podslushano.nl/privacy-statement-eu/</a></p>
</section>
"""

def _form_page(error: str = "", values: dict | None = None) -> str:
    values = values or {}
    def v(name: str) -> str:
        return html.escape(str(values.get(name) or ""), quote=True)

    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    body = f"""
<section class="hero">
<p class="eyebrow">Авторы Podslushano.nl</p>
<h1>Стать автором</h1>
<p class="lead">Анкета и правила для независимых авторов. Здесь сразу понятно, что добровольно, как устроены платные задания и где заканчивается редакционная работа Podslushano.nl.</p>
<div class="chips"><span class="chip">без графика</span><span class="chip">можно отказаться</span><span class="chip">каждая платная задача отдельно</span></div>
</section>
{_terms_sections()}
<section class="card">
<h2>Кто стоит за проектом</h2>
<div class="operator">
<div>Оператор</div><div><b>{_OPERATOR_NAME}</b></div>
<div>Проект</div><div>Podslushano.nl</div>
<div>KVK</div><div>{_KVK}</div>
<div>BTW</div><div>{_BTW}</div>
<div>Адрес</div><div>{_ADDRESS}</div>
<div>E-mail</div><div><a href="mailto:{_EMAIL}">{_EMAIL}</a></div>
<div>Сайт</div><div><a href="{_SITE}" target="_blank" rel="noopener">podslushano.nl</a></div>
</div>
</section>
<section class="card">
<h2>Анкета автора</h2>
{error_html}
<form method="post" action="/authors/agreement">
<div class="grid">
<div class="full"><label>ФИО полностью</label><input name="full_name" maxlength="200" value="{v("full_name")}" required autocomplete="name"></div>
<div><label>Город в Нидерландах</label><input name="city" maxlength="120" value="{v("city")}" required></div>
<div><label>E-mail</label><input type="email" name="email" maxlength="200" value="{v("email")}" required autocomplete="email"></div>
<div><label>Telegram</label><input name="telegram" maxlength="200" placeholder="@username или ссылка" value="{v("telegram")}" required></div>
<div><label>Instagram <span style="font-weight:500;color:#777">(если есть)</span></label><input name="instagram" maxlength="200" placeholder="@username или ссылка" value="{v("instagram")}"></div>
<div class="full"><label>На какой телефон снимаешь?</label><input name="phone_model" maxlength="120" placeholder="Например: iPhone 15 Pro" value="{v("phone_model")}" required></div>
</div>
<div class="check"><input type="checkbox" id="adult" name="adult" value="1" required><label for="adult">Мне 18 лет или больше.</label></div>
<div class="check"><input type="checkbox" id="accept" name="accept" value="1" required><label for="accept">Я прочитал(а) и принимаю условия независимого участия в Podslushano.nl, версия {AGREEMENT_VERSION} от {AGREEMENT_DATE}, включая правила платных заданий, конфиденциальности и работы с клиентами. Я понимаю, что отправка анкеты не означает автоматическое принятие в пул авторов и не создаёт гарантии заданий или дохода.</label></div>
<button type="submit">Принять условия и отправить анкету</button>
<p class="small">После отправки система зафиксирует дату, версию и контрольный хэш принятых условий. Хэш версии: {AGREEMENT_SHA256[:12]}…</p>
</form>
</section>
"""
    return _layout(body)


def _success_page(record_id: int, full_name: str) -> str:
    ref = f"PNL-AUTHOR-{record_id:05d}"
    body = f"""
<section class="hero">
<div class="ok">✓</div>
<p class="eyebrow">Готово</p>
<h1>Заявка получена</h1>
<p class="lead"><b>{html.escape(full_name)}</b>, анкета получена, а принятие условий версии {AGREEMENT_VERSION} зафиксировано.</p>
<div class="ref">{ref}</div>
</section>
<section class="card">
<h2>Что дальше</h2>
<p>Алекс добавит тебя в закрытый чат авторов и расскажет про ближайшие идеи, события и съёмки.</p>
<p class="small">Дата условий: {AGREEMENT_DATE} · SHA-256: {AGREEMENT_SHA256}</p>
</section>
"""
    return _layout(body, title="Условия приняты")


async def agreement_page(request: web.Request) -> web.Response:
    return web.Response(
        text=_form_page(),
        content_type="text/html",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def agreement_submit(request: web.Request) -> web.Response:
    data = await request.post()
    fields = {
        "full_name": (data.get("full_name") or "").strip(),
        "city": (data.get("city") or "").strip(),
        "email": (data.get("email") or "").strip().lower(),
        "telegram": (data.get("telegram") or "").strip(),
        "instagram": (data.get("instagram") or "").strip(),
        "phone_model": (data.get("phone_model") or "").strip(),
    }

    if not all(fields[k] for k in ("full_name", "city", "email", "telegram", "phone_model")):
        return web.Response(text=_form_page("Заполни обязательные поля.", fields), content_type="text/html", status=400)
    if len(fields["full_name"]) > 200 or len(fields["city"]) > 120 or len(fields["email"]) > 200:
        return web.Response(text=_form_page("Одно из полей слишком длинное.", fields), content_type="text/html", status=400)
    if not _EMAIL_RE.match(fields["email"]):
        return web.Response(text=_form_page("Укажи корректный e-mail.", fields), content_type="text/html", status=400)
    if data.get("adult") != "1":
        return web.Response(text=_form_page("Участие в этой форме доступно только с 18 лет.", fields), content_type="text/html", status=400)
    if data.get("accept") != "1":
        return web.Response(text=_form_page("Нужно принять условия участия.", fields), content_type="text/html", status=400)

    async with get_session() as session:
        existing = await session.scalar(
            select(AuthorAgreementAcceptance).where(
                func.lower(AuthorAgreementAcceptance.email) == fields["email"],
                AuthorAgreementAcceptance.agreement_version == AGREEMENT_VERSION,
            )
        )
        if existing is not None:
            return web.Response(
                text=_success_page(existing.id, existing.full_name),
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )

        record = AuthorAgreementAcceptance(
            full_name=fields["full_name"],
            city=fields["city"],
            email=fields["email"],
            telegram=fields["telegram"],
            instagram=fields["instagram"] or None,
            phone_model=fields["phone_model"],
            agreement_version=AGREEMENT_VERSION,
            agreement_sha256=AGREEMENT_SHA256,
            user_agent=(request.headers.get("User-Agent") or "")[:500] or None,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        record_id = record.id

    bot = request.app.get("bot")
    if bot is not None:
        msg = (
            "📝 <b>Новая заявка автора</b>\n\n"
            f"ФИО: {html.escape(fields['full_name'])}\n"
            f"Город: {html.escape(fields['city'])}\n"
            f"Telegram: {html.escape(fields['telegram'])}\n"
            f"Instagram: {html.escape(fields['instagram'] or '—')}\n"
            f"Телефон: {html.escape(fields['phone_model'])}\n"
            f"E-mail: {html.escape(fields['email'])}\n"
            f"Версия: {AGREEMENT_VERSION} · PNL-AUTHOR-{record_id:05d}"
        )
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_message(admin_id, msg)
            except Exception as exc:  # noqa: BLE001
                log.warning("Не уведомил админа о новом авторе: %s", exc)

    return web.Response(
        text=_success_page(record_id, fields["full_name"]),
        content_type="text/html",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def agreement_short(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound(location="/authors/agreement")


def install_routes(app: web.Application) -> None:
    app.router.add_get("/authors", agreement_short)
    app.router.add_get("/authors/agreement", agreement_page)
    app.router.add_post("/authors/agreement", agreement_submit)
