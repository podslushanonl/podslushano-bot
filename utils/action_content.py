"""Action-post layer for the Telegram channel.

Two posts per week replace the old short bot reminders. Each post has one
measurable action and opens the promised bot section through the existing
content deep-link attribution.
"""
from __future__ import annotations

from sqlalchemy import select

from database.db import get_session
from database.models import ContentPost
from handlers import content


ACTION_TEMPLATES = {
    "action_events": content.Template(
        "events", "events", "🎭 Что рядом со мной",
        "Иногда самое интересное на выходных проходит в двадцати минутах от дома — и узнаёшь об этом уже по чужим сторис.\n\n"
        "В боте можно открыть афишу именно для своего города и посмотреть, что происходит рядом в ближайшие дни.\n\n"
        "Не список на всю страну — начните со своего города 👇",
    ),
    "action_digest": content.Template(
        "digest", "digest", "🔔 Включить мою подборку",
        "Можно каждый четверг снова вспоминать: «А что вообще делать на выходных?»\n\n"
        "А можно один раз указать город, радиус и интересы — и получать подборку под себя. События, прогулки, полезное, объявления: только то, что вы выбрали.\n\n"
        "Настройка занимает пару минут 👇",
    ),
    "action_board": content.Template(
        "board", "board", "📋 Открыть доску",
        "Есть вещь, которую давно собираетесь продать? Ищете жильё, работу, велосипед или попутчика?\n\n"
        "Не обязательно ждать подходящего поста в чате. В боте есть доска объявлений: можно посмотреть актуальные карточки или разместить свою.\n\n"
        "Проверьте, что там есть сейчас 👇",
    ),
    "action_letter": content.Template(
        "utility", "letter", "📩 Разобрать моё письмо",
        "Есть письмо на нидерландском, которое лежит второй день, потому что непонятно: это просто информация или от вас уже чего-то ждут?\n\n"
        "Сфотографируйте его и отправьте боту. Он разберёт смысл, выделит действие и срок, если он указан.\n\n"
        "Можно проверить прямо сейчас 👇",
    ),
    "action_salary": content.Template(
        "utility", "salary", "🧮 Посчитать netto",
        "Видите в вакансии зарплату bruto и автоматически пытаетесь прикинуть, сколько из неё останется?\n\n"
        "Для этого в боте есть отдельный калькулятор. Введите сумму — получите ориентир netto по Нидерландам.\n\n"
        "Проверьте свою зарплату 👇",
    ),
    "action_notifications": content.Template(
        "notifications", "notifications", "🔔 Выбрать уведомления",
        "Бот не обязан писать вам обо всём подряд.\n\n"
        "Можно оставить только то, что действительно полезно: мероприятия рядом, планы на выходные, новые специалисты или другие нужные обновления.\n\n"
        "Выберите свои уведомления 👇",
    ),
    "action_specialists": content.Template(
        "specialists", "specialists", "🔎 Найти специалиста",
        "Кого сейчас сложнее всего найти: бухгалтера, мастера, юриста, психолога или кого-то ещё?\n\n"
        "Вместо поиска по старым сообщениям можно открыть ContactGuide и искать по профессии и городу.\n\n"
        "Введите, кто вам нужен 👇",
    ),
    "action_selfadd": content.Template(
        "commercial", "selfadd", "➕ Добавить свою карточку",
        "Если вы работаете с русскоязычными клиентами в Нидерландах, вас должны находить в тот момент, когда человеку уже нужна ваша услуга.\n\n"
        "В ContactGuide можно добавить свою карточку: категория, город, описание и прямые контакты. Оформление проходит внутри бота.\n\n"
        "Добавить себя в каталог 👇",
    ),
}

TUESDAY_ACTIONS = (
    "action_letter", "action_events", "action_salary", "action_board",
    "action_specialists", "action_digest", "action_notifications",
)
THURSDAY_ACTIONS = (
    "action_events", "action_board", "action_specialists", "action_digest",
    "action_notifications", "action_letter", "action_salary",
)

_original_seed = content.seed_content_calendar
_migrated = False


async def _migrate_future_action_slots() -> None:
    """Rewrite already-seeded future reminders; preserve sent history/analytics.

    Adjacent calendar entries must differ both by concrete action and by
    content_kind. This preserves the content-center invariant and avoids, for
    example, two utility posts (letter -> salary) next to each other.
    """
    global _migrated
    if _migrated:
        return

    now = content._local_now()
    async with get_session() as session:
        previous = (await session.scalars(
            select(ContentPost).where(
                ContentPost.scheduled_at < now,
                ContentPost.status != "skipped",
            ).order_by(ContentPost.scheduled_at.desc()).limit(1)
        )).first()
        last_action = previous.template_key if previous else ""
        last_kind = previous.content_kind if previous else ""

        rows = (await session.scalars(
            select(ContentPost).where(
                ContentPost.status.in_(("scheduled", "failed")),
                ContentPost.scheduled_at >= now,
            ).order_by(ContentPost.scheduled_at)
        )).all()

        for row in rows:
            weekday = row.scheduled_at.weekday()
            if weekday not in (1, 3):
                if row.template_key == "selfadd":
                    row.status = "skipped"
                    row.error_text = "replaced by two-action-post weekly strategy"
                    continue
                # Non-action calendar entries still participate in adjacency.
                last_action = row.template_key
                last_kind = row.content_kind
                continue

            rotation = TUESDAY_ACTIONS if weekday == 1 else THURSDAY_ACTIONS
            offset = (row.scheduled_at.date().toordinal() // 7) % len(rotation)
            candidates = rotation[offset:] + rotation[:offset]
            key = next(
                k for k in candidates
                if k != last_action and ACTION_TEMPLATES[k].kind != last_kind
            )
            template = ACTION_TEMPLATES[key]
            row.template_key = key
            row.content_kind = template.kind
            row.button_label = template.button
            row.error_text = None
            last_action = key
            last_kind = template.kind

        await session.commit()
    _migrated = True


async def _action_seed_content_calendar() -> None:
    await _original_seed()
    await _migrate_future_action_slots()


def install_action_templates() -> None:
    """Install two action posts/week and keep existing deep-link click analytics."""
    content.TEMPLATES.update(ACTION_TEMPLATES)
    content.TUESDAY_ROTATION = TUESDAY_ACTIONS
    content.THURSDAY_ROTATION = THURSDAY_ACTIONS
    content.seed_content_calendar = _action_seed_content_calendar
