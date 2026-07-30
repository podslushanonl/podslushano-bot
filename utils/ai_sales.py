"""AI Sales Manager для входящих рекламных заявок.

Анализирует заявку, готовит рекомендацию и ответ клиенту. Результат хранится
в Meta, чтобы администратор мог отправить предложенный ответ одной кнопкой.
"""
from __future__ import annotations

import html
import json
import logging

import config
from database.db import get_session
from database.models import Meta, Submission

log = logging.getLogger(__name__)

ADS_URL = "https://worker-production-ad76.up.railway.app/ads"
_META_PREFIX = "ai_sales:"

SYSTEM_PROMPT = f"""
Ты — AI Sales Manager русскоязычного медиа-сообщества Podslushano.nl в Нидерландах.
Ты анализируешь только входящие заявки на рекламу и сотрудничество.

Главная задача: помочь администратору решить, можно ли принимать рекламу, и
подготовить короткий готовый ответ клиенту на русском языке.

Правила бизнеса:
1. Обычные услуги, образование, репетиторы, мастера, магазины, мероприятия,
   вакансии и полезные сервисы обычно можно принимать.
2. Прямых конкурентов нужно отправлять на ручную проверку. Конкуренты:
   русскоязычные сообщества Нидерландов, медиа, Telegram-каналы и проекты,
   которые собирают ту же аудиторию; клубы знакомств, встречи, прогулки и
   комьюнити, конкурирующие с проектом Allo.
3. При сомнительном, незаконном, дискриминационном или потенциально мошенническом
   предложении рекомендовать отказ или дополнительную проверку.
4. Для одобренной стандартной заявки основной следующий шаг — отправить страницу,
   где клиент сам выбирает формат, дату и оплачивает: {ADS_URL}
5. Не выдумывай факты о клиенте. Не обещай публикацию до оплаты и модерации.
6. Ответ клиенту должен быть коротким, вежливым и естественным, без лишних
   объяснений внутренней кухни.

Верни ТОЛЬКО валидный JSON без markdown:
{{
  "decision": "approve" | "review" | "reject",
  "risk": "low" | "medium" | "high",
  "category": "короткая категория",
  "competitor": true | false,
  "recommended_format": "название формата или 'выбор на странице'",
  "reason": "1-3 коротких предложения для администратора",
  "reply": "готовый ответ клиенту"
}}
""".strip()


def enabled() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


async def analyze_ad_submission(submission: Submission) -> dict | None:
    """Анализирует рекламную заявку и сохраняет результат для кнопки отправки."""
    if submission.type != "ad" or not enabled():
        return None

    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model=config.AI_CHAT_MODEL,
            max_tokens=900,
            temperature=0.2,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Заявка №{submission.id}\n"
                        f"Username: @{submission.username or 'нет'}\n"
                        f"Текст заявки:\n{submission.text or '—'}"
                    ),
                }
            ],
        )
        raw = "".join(
            block.text for block in response.content
            if getattr(block, "type", None) == "text"
        ).strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].lstrip()
        result = json.loads(raw)
        if result.get("decision") not in {"approve", "review", "reject"}:
            raise ValueError("invalid decision")
        if not isinstance(result.get("reply"), str) or not result["reply"].strip():
            raise ValueError("empty reply")
        await save_analysis(submission.id, result)
        return result
    except Exception as exc:  # noqa: BLE001
        log.warning("AI Sales Manager не смог разобрать заявку %s: %s", submission.id, exc)
        return None


async def save_analysis(submission_id: int, result: dict) -> None:
    async with get_session() as session:
        await session.merge(
            Meta(
                key=f"{_META_PREFIX}{submission_id}",
                value=json.dumps(result, ensure_ascii=False),
            )
        )
        await session.commit()


async def load_analysis(submission_id: int) -> dict | None:
    async with get_session() as session:
        item = await session.get(Meta, f"{_META_PREFIX}{submission_id}")
    if not item or not item.value:
        return None
    try:
        return json.loads(item.value)
    except json.JSONDecodeError:
        return None


def format_admin_block(result: dict) -> str:
    decision = {
        "approve": "🟢 Одобрить",
        "review": "🟡 Проверить вручную",
        "reject": "🔴 Отказать",
    }.get(result.get("decision"), "🟡 Проверить вручную")
    competitor = "Да" if result.get("competitor") else "Нет"
    reply = html.escape(str(result.get("reply", "")).strip())
    return (
        "\n\n🤖 <b>AI Sales Manager</b>\n"
        f"<b>Решение:</b> {decision}\n"
        f"<b>Категория:</b> {html.escape(str(result.get('category', '—')))}\n"
        f"<b>Конкурент:</b> {competitor}\n"
        f"<b>Риск:</b> {html.escape(str(result.get('risk', '—')))}\n"
        f"<b>Рекомендация:</b> {html.escape(str(result.get('recommended_format', '—')))}\n"
        f"<b>Почему:</b> {html.escape(str(result.get('reason', '—')))}\n\n"
        f"<b>Готовый ответ:</b>\n{reply}"
    )
