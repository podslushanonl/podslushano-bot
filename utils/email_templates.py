"""Тексты писем podslushano.nl. Каждая функция возвращает (тема, html, текст).

Тон: дружелюбно, коротко, по делу, без официоза. Лосёнок — для уюта, не в каждом абзаце.
Пять основных сценариев:
  1. digest()            — «Неделя в Нидерландах» / полезный гайд
  2. payment_received()  — оплата получена (КонтактGuide, афиша и т. д.) + счёт во вложении
  3. welcome_week()      — подписка на пятничную рассылку
  4. card_renewal() / card_expired() / tax_deadline() — напоминания
  5. cabinet_login()     — вход в кабинет бизнеса по ссылке
"""
from __future__ import annotations

from utils.email_brand import (
    box, bullets, esc, facts, p, render_email, site, small, steps, text_version,
)


# ---------------------------------------------------------------- 1. Дайджест

def digest(*, week_label: str, items: list[dict], events: list[dict] | None = None,
           unsubscribe_url: str | None = None) -> tuple[str, str, str]:
    """items: [{"title", "text", "url"}], events: [{"title", "when", "url"}]."""
    subject = f"🇳🇱 Неделя в Нидерландах: главное за 3 минуты · {week_label}"
    pre = "Короткие новости без политики, куда сходить на выходных и одна полезность."
    news = "".join(
        f'<p style="margin:0 0 6px;font:700 17px/1.35 -apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#0D1117;">'
        f'<a href="{esc(it["url"])}" style="color:#0D1117;text-decoration:none;">{esc(it["title"])}</a></p>'
        + p(esc(it["text"])) for it in items[:6])
    ev = ""
    if events:
        ev = ('<p style="margin:8px 0 10px;font:700 12px/1 -apple-system,Segoe UI,Roboto,Arial,sans-serif;'
              'letter-spacing:.08em;text-transform:uppercase;color:#FF5A1F;">Куда сходить</p>'
              + bullets([f'<a href="{esc(e["url"])}" style="color:#0D1117;font-weight:600;">{esc(e["title"])}</a>'
                         f' · {esc(e["when"])}' for e in events[:5]]))
    body = (p("Привет! Лосёнок собрал для вас всё важное за неделю. Налейте koffie, это на три минуты.")
            + news + ev)
    html = render_email(eyebrow="Неделя в Нидерландах", title=f"Главное за неделю · {esc(week_label)}",
                        preheader=pre, body=body, cta=("Все новости на сайте", site("/news/")),
                        reason="Вы подписаны на пятничную рассылку «Неделя в Нидерландах».",
                        unsubscribe_url=unsubscribe_url)
    text = text_version(f"Главное за неделю · {week_label}",
                        [f'{it["title"]}\n{it["text"]}\n{it["url"]}' for it in items[:6]],
                        ("Все новости", site("/news/")), unsubscribe_url)
    return subject, html, text


def guide(*, title: str, intro: str, points: list[str], url: str, cta: str = "Скачать гайд",
          unsubscribe_url: str | None = None) -> tuple[str, str, str]:
    subject = f"📘 {title}: коротко и по делу"
    body = p(esc(intro)) + bullets([esc(x) for x in points]) + small(
        "Это информационный разбор, а не индивидуальная консультация.")
    html = render_email(eyebrow="Полезный гайд", title=esc(title), preheader=intro[:110], body=body,
                        cta=(cta, url), unsubscribe_url=unsubscribe_url,
                        reason="Вы подписаны на рассылку podslushano.nl.")
    return subject, html, text_version(title, [intro, *points], (cta, url), unsubscribe_url)


# ---------------------------------------------------------------- 2. Оплата получена

NEXT_STEPS = {
    "afisha": [("Проверяем событие", "Наша команда посмотрит описание и постер. Обычно это быстро, максимум 5 рабочих дней."),
               ("Публикуем в афише", "Событие появится на podslushano.nl/events и в боте."),
               ("Пишем вам", "Пришлём письмо со ссылкой на опубликованное событие.")],
    "guide": [("Проверяем карточку", "Смотрим, что всё понятно и контакты рабочие. До 5 рабочих дней."),
              ("Карточка в КонтактGuide", "Вас начнут находить на сайте и в нашем боте."),
              ("Кабинет бизнеса", "Менять текст, фото и продлевать можно сами, в кабинете на сайте.")],
}


def payment_received(*, kind: str, item: str, amount: str, invoice_no: str | None = None,
                     name: str = "") -> tuple[str, str, str]:
    """kind: afisha | guide | other. Счёт (factuur) идёт вложением к этому письму."""
    label = {"afisha": "Событие в афише", "guide": "Карточка в КонтактGuide"}.get(kind, "Заказ")
    subject = f"✅ Оплата получена: {item}"
    hello = f"Привет, {esc(name)}!" if name and name != "Гость" else "Привет!"
    rows = [(label, esc(item)), ("Сумма", f"€{esc(amount)}")]
    if invoice_no:
        rows.append(("Счёт (factuur)", f"№{esc(invoice_no)}, во вложении"))
    body = p(f"{hello} Оплату получили, спасибо, что вы с нами.") + facts(rows)
    if kind in NEXT_STEPS:
        body += ('<p style="margin:6px 0 10px;font:700 15px/1.4 -apple-system,Segoe UI,Roboto,Arial,sans-serif;'
                 'color:#0D1117;">Что дальше</p>' + steps(NEXT_STEPS[kind]))
    body += small("Остались вопросы? Просто ответьте на это письмо, его прочитает живой человек.")
    cta = {"afisha": ("Открыть афишу", site("/events/")), "guide": ("Открыть кабинет бизнеса", site("/cabinet/"))}.get(kind)
    html = render_email(eyebrow="Оплата получена", title="Всё получили, спасибо!",
                        preheader=f"€{amount} · {item}. Рассказываем, что будет дальше.", body=body, cta=cta,
                        reason="Это подтверждение вашего заказа на podslushano.nl.")
    text = text_version("Оплата получена", [f"{label}: {item}", f"Сумма: €{amount}",
                                            *(f"{t}. {d}" for t, d in NEXT_STEPS.get(kind, []))], cta)
    return subject, html, text


def afisha_published(*, title: str, url: str) -> tuple[str, str, str]:
    subject = f"🎉 Ваше событие в афише: {title}"
    body = (p(f"Готово! «{esc(title)}» опубликовано в афише podslushano.nl. Через несколько минут оно появится на сайте.")
            + box("Совет: поделитесь ссылкой на событие в своих соцсетях, так его увидит больше людей."))
    html = render_email(eyebrow="Афиша", title="Событие опубликовано", preheader="Ссылка внутри, можно делиться.",
                        body=body, cta=("Открыть событие", url), reason="Вы добавили событие в афишу podslushano.nl.")
    return subject, html, text_version("Событие опубликовано", [f"«{title}» в афише podslushano.nl."], ("Открыть", url))


def afisha_rejected(*, title: str, contact: str) -> tuple[str, str, str]:
    subject = f"Событие «{title}» не прошло проверку"
    body = (p(f"К сожалению, «{esc(title)}» мы не можем добавить в афишу. Оплату вернём в ближайшие дни.")
            + p(f"Если хотите уточнить причину или исправить описание, напишите нам: "
                f'<a href="mailto:{esc(contact)}" style="color:#FF5A1F;font-weight:600;">{esc(contact)}</a>.'))
    html = render_email(eyebrow="Афиша", title="Не получилось опубликовать", preheader="Оплату вернём. Подробности внутри.",
                        body=body, reason="Вы добавляли событие в афишу podslushano.nl.")
    return subject, html, text_version("Не получилось опубликовать", [f"«{title}»: оплату вернём. Вопросы: {contact}"])


def donation_thanks(*, amount: str, monthly: bool = False, cancel_url: str | None = None) -> tuple[str, str, str]:
    if monthly:
        subject = "💛 Спасибо за ежемесячный вклад в развитие podslushano.nl"
        body = (p(f"Каждый месяц €{esc(amount)} будут работать на podslushano.nl: новости по-русски, новые разделы, сервер.")
                + p("Лосёнок отдельно передаёт спасибо. Без вас нас бы не было.")
                + small(f'Отменить можно в любой момент, в один клик: <a href="{esc(cancel_url)}" style="color:#6A7280;">'
                        "отменить ежемесячный вклад</a>."))
    else:
        subject = "💛 Спасибо за вклад в развитие podslushano.nl"
        body = (p(f"€{esc(amount)} уже работают на podslushano.nl: новости по-русски, новые разделы и сервер.")
                + p("Лосёнок отдельно передаёт спасибо. Gezellig, что вы с нами!"))
    html = render_email(eyebrow="Вклад в развитие", title="Спасибо, правда", hero="deer",
                        preheader="Ваш вклад уже работает на сообщество.", body=body,
                        cta=("На сайт", site()), reason="Вы сделали вклад в развитие podslushano.nl.")
    return subject, html, text_version("Спасибо за вклад", [f"€{amount}" + (" каждый месяц" if monthly else "")],
                                       ("Отменить", cancel_url) if monthly and cancel_url else None)


# ---------------------------------------------------------------- 3. Welcome

def welcome_week(*, unsubscribe_url: str, gift_url: str) -> tuple[str, str, str]:
    subject = "👋 Добро пожаловать в «Неделю в Нидерландах»!"
    body = (p("Привет! Это лосёнок из podslushano.nl. Спасибо, что подписались, теперь будем видеться по пятницам.")
            + p("<b>Что будет в каждом письме:</b>")
            + bullets(["Главные новости недели, коротко и без политики",
                       "Куда сходить на выходных: концерты, стендап, прогулки allowalks",
                       "Одна полезность о жизни здесь: налоги, toeslagen, жильё, документы",
                       "Новые русскоязычные специалисты рядом с вами"])
            + box("<b>Подарок за подписку:</b> наш гайд «Налоги и субсидии 2026». Всё про aangifte, "
                  "toeslagen и льготы простым языком.", "warm"))
    html = render_email(eyebrow="Неделя в Нидерландах", title="Будем на связи по пятницам", hero="deer",
                        preheader="Внутри подарок: гайд «Налоги и субсидии 2026».", body=body,
                        cta=("Забрать гайд", gift_url),
                        after_cta=small("Три минуты чтения раз в неделю. Без спама, обещаем."),
                        reason="Вы подписались на рассылку «Неделя в Нидерландах» на podslushano.nl.",
                        unsubscribe_url=unsubscribe_url)
    text = text_version("Добро пожаловать в «Неделю в Нидерландах»",
                        ["По пятницам: новости недели, куда сходить, одна полезность и новые специалисты.",
                         "Подарок: гайд «Налоги и субсидии 2026»."], ("Забрать гайд", gift_url), unsubscribe_url)
    return subject, html, text


def confirm_week(*, confirm_url: str) -> tuple[str, str, str]:
    subject = "Подтвердите подписку на «Неделю в Нидерландах»"
    html = render_email(title="Остался один клик", preheader="Подтвердите почту, и первый выпуск придёт в пятницу.",
                        body=p("Нажмите кнопку, чтобы подтвердить подписку. Это защита от чужих подписок на вашу почту."),
                        cta=("Подтвердить подписку", confirm_url),
                        after_cta=small("Не подписывались? Просто удалите письмо, больше мы не напишем."),
                        reason="Кто-то указал эту почту в форме подписки на podslushano.nl.")
    return subject, html, text_version("Подтвердите подписку", [], ("Подтвердить", confirm_url))


# ---------------------------------------------------------------- 4. Напоминания

def card_renewal(*, name: str, until: str, plan: str, url: str) -> tuple[str, str, str]:
    subject = f"⏳ «{name}» в КонтактGuide: осталось 7 дней"
    body = (p("Привет! Напоминаем заранее, чтобы клиенты и дальше находили вас без перерыва.")
            + facts([("Карточка", esc(name)), ("Действует до", esc(until)), ("Продление", esc(plan))])
            + p("Продлить можно за пару минут в кабинете бизнеса: ссылка ниже уже входит в кабинет."))
    html = render_email(eyebrow="КонтактGuide", title="Карточка скоро уйдёт на паузу",
                        preheader=f"Действует до {until}. Продлите заранее, без перерыва в поиске.",
                        body=body, cta=("Продлить карточку", url),
                        after_cta=small("Уже продлили? Спасибо! Это письмо можно пропустить. Ссылка для входа действует 3 дня."),
                        reason="Вы размещаете карточку в КонтактGuide podslushano.nl.")
    return subject, html, text_version("Карточка скоро уйдёт на паузу", [f"«{name}» действует до {until}."],
                                       ("Продлить", url))


def card_expired(*, name: str, plan: str, url: str) -> tuple[str, str, str]:
    subject = f"«{name}» скрыта из поиска КонтактGuide"
    body = (p(f"Срок размещения «{esc(name)}» закончился, поэтому карточка временно скрыта из поиска на сайте и в боте.")
            + p(f"Вернуть её можно в любой момент, всё сохранено: текст, фото, отзывы. Продление: {esc(plan)}."))
    html = render_email(eyebrow="КонтактGuide", title="Карточка на паузе", preheader="Всё сохранено, вернуть можно в пару кликов.",
                        body=body, cta=("Вернуть карточку в гайд", url),
                        reason="Вы размещали карточку в КонтактGuide podslushano.nl.")
    return subject, html, text_version("Карточка на паузе", [f"«{name}» скрыта из поиска."], ("Вернуть", url))


def tax_deadline(*, deadline: str, url: str, unsubscribe_url: str | None = None) -> tuple[str, str, str]:
    subject = f"🗓 Aangifte до {deadline}: спокойно, успеваем"
    body = (p("Привет! Лосёнок напоминает: до срока подачи налоговой декларации (aangifte inkomstenbelasting) "
              f"осталось немного, крайний день {esc(deadline)}.")
            + p("<b>Что подготовить:</b>")
            + bullets(["DigiD для входа в Mijn Belastingdienst", "Jaaropgaaf от работодателя",
                       "Выписки по счетам и ипотеке, если есть", "Чеки на вычеты: учёба, медицина, пожертвования"])
            + box("Не успеваете? Можно попросить отсрочку (uitstel) на сайте Belastingdienst, это нормально и бесплатно."))
    html = render_email(eyebrow="Напоминание", title="Налоговая декларация: пора", preheader="Чек-лист на 2 минуты и как взять отсрочку.",
                        body=body, cta=("Открыть гайд по налогам", url), unsubscribe_url=unsubscribe_url,
                        reason="Вы подписаны на рассылку podslushano.nl.")
    return subject, html, text_version("Налоговая декларация: пора", [f"Крайний срок: {deadline}."], ("Гайд", url),
                                       unsubscribe_url)


# ---------------------------------------------------------------- 5. Вход в кабинет

def cabinet_login(*, link: str) -> tuple[str, str, str]:
    subject = "🔑 Вход в кабинет бизнеса podslushano.nl"
    body = (p("Нажмите кнопку, чтобы войти. Пароль не нужен.")
            + small("Ссылка одноразовая и действует 1 час. Если вы не запрашивали вход, просто удалите письмо: "
                    "без этой ссылки в кабинет никто не попадёт."))
    html = render_email(title="Вход в кабинет", preheader="Ссылка действует 1 час.", body="", cta=("Войти в кабинет", link),
                        after_cta=body, reason="Кто-то запросил вход в кабинет бизнеса для этой почты.")
    return subject, html, text_version("Вход в кабинет бизнеса", ["Ссылка действует 1 час."], ("Войти", link))
