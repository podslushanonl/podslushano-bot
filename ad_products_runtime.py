"""Canonical advertising products for the public /ads checkout.

AD_PRODUCTS.md is the source of truth for product meaning. Legacy definitions
remain resolvable for already-created bookings, while the three public product
IDs below power new sales.
"""
from __future__ import annotations

import config


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
            "badge": "Один повод · одна дата",
            "lead": "Один рекламный запуск вокруг конкретного предложения в выбранный день.",
            "details": [
                "1 основная публикация Instagram: пост, карусель или Reel при наличии подходящего готового видео",
                "2 Instagram Stories как продолжение основной подачи",
                "1 отдельный нативный Telegram-пост",
                "редакционная адаптация текста, заголовка, структуры и CTA",
                "проверка ссылок и контактов перед публикацией",
            ],
            "who": "мероприятиям, акциям, открытиям, новым услугам, запускам и предложениям с конкретным дедлайном",
            "options": [{"key": "std", "label": "1 рекламный выход", "price": "99.00"}],
            "dates": 1,
            "lead_days": 2,
            "public": True,
        },
        "ad_promotion": {
            "name": "Продвижение",
            "badge": "4 выхода · 60 дней",
            "lead": "Четыре последовательных рекламных выхода в Instagram в течение двух месяцев.",
            "details": [
                "4 основные публикации Instagram в течение 60 дней",
                "8 Instagram Stories — по 2 к каждому основному выходу",
                "4 разные темы или угла подачи, чтобы публикации не дублировали друг друга",
                "редакционная адаптация текстов и визуальных материалов клиента",
                "закрепление одной основной публикации или Reel в профиле Instagram на 3 дня",
                "Telegram в этот продукт не входит",
            ],
            "who": "специалистам, услугам, локальным бизнесам и проектам, которым важно несколько раз появиться перед аудиторией",
            "options": [{"key": "std", "label": "Продвижение / 60 дней", "price": "180.00"}],
            "dates": 4,
            "lead_days": 2,
            "public": True,
        },
        "ad_campaign": {
            "name": "Под ключ",
            "badge": "Мы создаём рекламу за вас",
            "lead": "Вы даёте продукт, факты и исходники — Podslushano.nl придумывает концепцию, создаёт материалы и проводит кампанию.",
            "details": [
                "стратегический мини-бриф и одна рекламная концепция",
                "3 разные основные единицы Instagram-контента, создаваемые Podslushano.nl",
                "форматы выбираются по задаче: Reel, карусель или нативный пост; минимум 1 Reel при наличии пригодного видео",
                "6 Instagram Stories — по 2 вокруг каждой рекламной волны",
                "2 отдельные Telegram-публикации в разные моменты кампании",
                "сценарии, тексты, структура, базовый дизайн и монтаж из материалов клиента",
                "закрепление одной сильной Instagram-публикации на 3 дня",
                "Contact Guide Premium на 2 месяца",
                "корректировка подачи после первой волны и итоговая статистика",
            ],
            "who": "брендам, приложениям, сервисам, образовательным продуктам и сложным услугам, которым нужно создать рекламу под ключ",
            "options": [{"key": "std", "label": "Под ключ / до 45 дней", "price": "299.00"}],
            # Customer chooses only campaign start. Remaining dates are agreed
            # after the brief and are not reserved through checkout.
            "dates": 1,
            "lead_days": 7,
            "public": True,
        },
    }
)
