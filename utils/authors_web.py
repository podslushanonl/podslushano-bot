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

AGREEMENT_VERSION = "1.0"
AGREEMENT_DATE = "10.10.2026"
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

_OPERATOR_NAME = "Aleksei Maksimovich Egorov"
_KVK = "98882317"
_BTW = "NL005359099B74"
_ADDRESS = "Karel Doormanstraat 63, 5342 TJ Oss, Nederland"
_EMAIL = "podslushano.nl@gmail.com"
_SITE = "https://www.podslushano.nl"

_AGREEMENT_CANONICAL = f"""
Podslushano.nl Author Terms v{AGREEMENT_VERSION} dated {AGREEMENT_DATE}.
Operator: {_OPERATOR_NAME}; KVK {_KVK}; BTW {_BTW}; {_ADDRESS}; {_EMAIL}.

1. Status and editorial control.
The author participates as an independent contributor, not an employee. There is no fixed schedule,
minimum output, guaranteed assignments, salary or guaranteed income. The founder and editor-in-chief
of Podslushano.nl is Aleksei Maksimovich Egorov. Final editorial, commercial and publication decisions
remain with Podslushano.nl.

2. Organic content.
The author may voluntarily propose and create stories, video, photos, observations and local reports.
The author may refuse any non-commercial or commercial task.

3. Events and invitations.
Podslushano.nl may offer tickets, invitations, accreditation or other access to concerts, festivals,
events and venues. Such benefits are not guaranteed compensation. Where content is expected in return,
that expectation is agreed in advance.

4. Commercial integrations.
Commercial requests and advertiser negotiations are managed by Podslushano.nl. If an author is involved
in a paid integration, the author's fee/share and deliverables are agreed before the task. The author
may refuse. No payment is owed for a commercial task unless Podslushano.nl and the author agreed it.

5. Confidentiality.
Internal chat content, advertiser and partner contacts obtained through the project, pricing, discounts,
commercial terms, analytics, unpublished plans, workflows, access credentials and internal feedback are
confidential. They may not be shared outside the team without permission. This duty continues for
24 months after cooperation ends for non-public commercial and operational information.

6. Non-circumvention.
For 12 months after the author's last work with a specific advertiser or partner first introduced to the
author through Podslushano.nl, the author will not knowingly bypass Podslushano.nl to solicit or contract
directly with that contact for substantially similar advertising services without written permission.
This does not apply to relationships demonstrably existing before the introduction by Podslushano.nl.

7. Own projects.
The author remains free to run personal social media, build a personal brand and earn independently,
provided they do not misuse Podslushano.nl confidential information, access, brand assets or project-originated
commercial relationships.

8. Content rights.
The author confirms they have the right to submit the content. By submitting content for Podslushano.nl,
the author grants Podslushano.nl a non-exclusive, worldwide, royalty-free licence to edit, format, publish,
repost and archive that content across Podslushano.nl channels and promotional materials. Commercial
campaign content may also be used by the relevant advertiser within the agreed campaign scope.

9. Team access and conduct.
Access is role-based and may be changed or withdrawn at any time. Passwords and master/admin access are
not automatically provided to authors. The author must not present themselves as owner or authorized
commercial representative of Podslushano.nl unless explicitly authorized.

10. Ending cooperation.
Either side may stop cooperation at any time. Already accepted paid tasks should be completed or otherwise
closed by mutual agreement. On exit, project access and unpublished internal materials must be deleted/returned.

11. Data.
Podslushano.nl stores the author's name, city, email, Telegram, optional Instagram, phone model, agreement
version/hash and acceptance timestamp for team administration and evidence of acceptance. Data is processed
for taking steps toward/performing this collaboration and legitimate administrative interests. Financial
records may be retained where legally required.

12. Law.
Dutch law applies. The parties first try to resolve disputes informally; if that fails, the competent
court in the Netherlands has jurisdiction subject to mandatory law.
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
<h2>Как устроено участие</h2>
<p>Мы собираем сеть авторов из разных городов Нидерландов. Формат свободный: увидел что-то интересное — снял; удивило — рассказал; есть мнение — поделился.</p>
<ul>
<li>нет фиксированного графика и обязательного количества сторис;</li>
<li>нет гарантированной зарплаты или гарантированного количества задач;</li>
<li>от любого задания можно отказаться;</li>
<li>финальные редакционные и коммерческие решения остаются за Podslushano.nl.</li>
</ul>
</section>

<section class="card">
<h2>Что получает автор</h2>
<ul>
<li>доступ к аудитории Podslushano.nl и возможность развивать собственную узнаваемость;</li>
<li>приглашения и билеты на концерты, фестивали и другие события, когда они доступны;</li>
<li>возможность участвовать в коммерческих съёмках и рекламных интеграциях за оплату;</li>
<li>общий закрытый чат авторов для идей, планирования, событий и съёмок.</li>
</ul>
<p class="note">Билеты и приглашения не являются фиксированной оплатой и не гарантируются. Если за приглашение ожидается контент, это проговаривается заранее.</p>
</section>

<section class="card">
<h2>Реклама и деньги</h2>
<p>Переговоры с рекламодателями, цены и коммерческие договорённости ведёт Podslushano.nl.</p>
<p>Если для интеграции нужен автор — например, съёмка ресторана, события или бизнеса в его городе — <b>сумма автору и объём задачи согласовываются заранее</b>. Автор может отказаться.</p>
<p>Автор не обязан выполнять коммерческую работу бесплатно.</p>
</section>

<section class="card">
<h2>Редакционная структура</h2>
<p><b>Основатель и главный редактор — Aleksei Maksimovich Egorov.</b> Он определяет стратегию проекта, редакционные стандарты, публикацию материалов, коммерческую политику и уровень доступов.</p>
<p>Авторы получают только те доступы и внутреннюю информацию, которые необходимы для их задач. Пароли, master/admin-доступы, CRM, полная клиентская база, финансовая модель и другие чувствительные данные автоматически авторам не предоставляются.</p>
</section>

<section class="card">
<h2>Конфиденциальность</h2>
<p>Нельзя передавать вне команды без разрешения:</p>
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
<p>Автор может вести свой блог, развивать личный бренд и самостоятельно зарабатывать.</p>
<p>При этом контакт рекламодателя или партнёра, с которым автор познакомился именно через Podslushano.nl, нельзя сознательно уводить из проекта и заключать с ним напрямую аналогичную рекламную сделку в обход Podslushano.nl без письменного разрешения в течение 12 месяцев после последней совместной работы с этим контактом.</p>
<p>Это ограничение не касается клиентов и связей, которые у автора были до знакомства через Podslushano.nl.</p>
</section>

<section class="card">
<h2>Контент и права</h2>
<p>Автор подтверждает, что имеет право передавать присланные фото, видео и тексты.</p>
<p>Передавая материал для Podslushano.nl, автор предоставляет проекту неисключительное право редактировать, оформлять, публиковать, повторно размещать и хранить этот материал в каналах Podslushano.nl и материалах о самом проекте.</p>
<p>Контент, созданный для оплаченной рекламной интеграции, также может использоваться соответствующим рекламодателем в рамках согласованной кампании.</p>
</section>

<section class="card">
<h2>Прекращение сотрудничества</h2>
<p>Любая сторона может прекратить участие в любой момент. Уже подтверждённые коммерческие задачи закрываются по ранее согласованным условиям либо отдельно договариваются сторонами.</p>
<p>После выхода из команды автор перестаёт представляться действующим автором Podslushano.nl, а выданные доступы отзываются.</p>
</section>

<section class="card">
<h2>Персональные данные и право</h2>
<p>Для работы команды и фиксации принятия условий мы сохраняем данные из формы, версию и контрольный хэш условий, а также дату принятия. Основание обработки — подготовка/исполнение сотрудничества и законный интерес в администрировании и подтверждении договорённостей.</p>
<p>Применяется право Нидерландов. Сначала стороны стараются решить спор напрямую; при невозможности — спор рассматривается компетентным судом Нидерландов с учётом обязательных норм закона.</p>
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
<p class="eyebrow">Команда Podslushano.nl</p>
<h1>Стать автором</h1>
<p class="lead">Живёшь в Нидерландах и хочешь показывать свой город, события и то, что замечаешь вокруг? Ниже — понятные условия участия без мелкого шрифта.</p>
<div class="chips"><span class="chip">свободный формат</span><span class="chip">ивенты и концерты</span><span class="chip">оплачиваемые рекламные съёмки</span></div>
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
<h2>Принять условия</h2>
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
<div class="check"><input type="checkbox" id="accept" name="accept" value="1" required><label for="accept">Я прочитал(а) и принимаю условия участия автора Podslushano.nl, версия {AGREEMENT_VERSION} от {AGREEMENT_DATE}, включая правила конфиденциальности и коммерческого взаимодействия.</label></div>
<button type="submit">Принять и присоединиться</button>
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
<h1>Ты в системе</h1>
<p class="lead"><b>{html.escape(full_name)}</b>, принятие условий версии {AGREEMENT_VERSION} зафиксировано.</p>
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
            "✍️ <b>Новый автор принял условия</b>\n\n"
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
