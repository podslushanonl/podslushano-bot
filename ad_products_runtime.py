"""Canonical advertising products for the public /ads checkout.

The source of truth for product meaning is AD_PRODUCTS.md.  This module keeps
legacy product definitions available for already-created bookings while adding
the new public product IDs used by the redesigned /ads page.

Imported once during bot startup, before handlers/webserver are imported.
"""
from __future__ import annotations

import config


# Historical products remain resolvable by invoices, payment webhooks, Calendar
# and old bookings, but must never be offered by the new public /ads UI.
for _legacy_id in (
    "expert",
    "promo",
    "tg",
    "afisha",
    "afisha_plus",
    "numr_campaign",
):
    if _legacy_id in config.AD_FORMATS:
        config.AD_FORMATS[_legacy_id]["private"] = True
        config.AD_FORMATS[_legacy_id]["archived"] = _legacy_id != "numr_campaign"


config.AD_FORMATS.update(
    {
        "ad_single": {
            "name": "Рекламный выход",
            "badge": "Одно предложение · одна дата",
            "lead": (
                "Один сильный рекламный выход вокруг конкретного предложения "
                "в выбранный день."
            ),
            "details": [
                "1 основная публикация Instagram: пост, карусель или Reel при наличии подходящего видео",
                "2 Instagram Stories, которые продолжают основную рекламную идею",
                "1 отдельная нативная публикация в Telegram",
                "редакционная адаптация текста, структуры и одного основного CTA",
                "проверка ссылок и контактов перед публикацией",
            ],
            "who": (
                "мероприятиям, открытиям, акциям, новым услугам, запускам, "
                "продаже билетов и предложениям с конкретным дедлайном"
            ),
            "options": [
                {"key": "std", "label": "1 рекламный выход", "price": "99.00"}
            ],
            "dates": 1,
            "lead_days": 2,
            "public": True,
        },
        "ad_promotion": {
            "name": "Продвижение",
            "badge": "4 касания · 60 дней",
            "lead": (
                "Два месяца последовательного знакомства аудитории с вашим бизнесом: "
                "каждый выход решает отдельную рекламную задачу."
            ),
            "details": [
                "4 основные публикации Instagram с четырьмя разными углами подачи",
                "касание 1: знакомство — кто вы, что делаете и кому это полезно",
                "касание 2: проблема или кейс — узнаваемая ситуация и ваше решение",
                "касание 3: доверие — кейс, FAQ, процесс или снятие главного возражения",
                "касание 4: действие — конкретное предложение и понятный CTA",
                "8 Instagram Stories — по 2 к каждой основной публикации",
                "1 отдельная нативная публикация в Telegram в сильной точке кампании",
                "редакционная разработка четырёх углов, CTA и распределения касаний",
            ],
            "who": (
                "специалистам, услугам, локальным бизнесам и проектам, которым "
                "одного рекламного выхода недостаточно"
            ),
            "options": [
                {"key": "std", "label": "Продвижение / 60 дней", "price": "150.00"}
            ],
            "dates": 4,
            "lead_days": 2,
            "public": True,
        },
        "ad_campaign": {
            "name": "Кампания под ключ",
            "badge": "Стратегия + производство · 60 дней",
            "lead": (
                "Вы даёте продукт, факты и исходники — Podslushano.nl разрабатывает "
                "концепцию, создаёт контент, ведёт кампанию и корректирует её по ходу."
            ),
            "details": [
                "стратегический мини-бриф: аудитория, проблема, преимущества, возражения и CTA",
                "4 основные единицы Instagram-контента: базово 2 Reel + 2 карусели / поста",
                "12 Instagram Stories вокруг четырёх рекламных волн",
                "2 отдельные нативные публикации в Telegram",
                "сценарии, тексты, структура каруселей, базовый дизайн и монтаж Reels из материалов клиента",
                "закрепление одной сильной Instagram-публикации на 3 дня",
                "возможность ссылки клиента на Links-странице на период кампании, если технически доступно",
                "промежуточный анализ после первых двух выходов и корректировка следующих",
                "итоговая сводка по доступным метрикам",
            ],
            "who": (
                "приложениям, сервисам, образовательным продуктам, брендам и сложным "
                "услугам, которым нужна не публикация, а рекламная работа под ключ"
            ),
            "options": [
                {"key": "std", "label": "Кампания под ключ / 60 дней", "price": "299.00"}
            ],
            # The customer chooses only a campaign start date.  The 60-day
            # media plan is produced after the strategic brief.
            "dates": 1,
            "lead_days": 7,
            "public": True,
        },
    }
)
