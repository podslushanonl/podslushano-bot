"""Порядок в рубриках сайта: все новости — в одной рубрике «Новости», тема — меткой.

Раньше бот клал каждую новость в подрубрику («новости → Безопасность», «→ Транспорт» …).
/wp_rubrics (админ, личка) показывает, что куда переедет, и ничего не меняет; кнопка
«Перенести» переносит записи: рубрика «Новости» вместо подрубрики, название подрубрики —
меткой. Прочие рубрики записи (например «Справочник») не трогаются. Подрубрики не удаляются:
их адреса уже знает Google. Повторный запуск безопасен — переносить будет нечего.
"""
import asyncio
import html
import logging
from collections import Counter

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from utils import wordpress as wp

log = logging.getLogger(__name__)

NEWS_NAME = "Новости"
PAUSE_SECONDS = 1.0  # между записями: хостинг сайта слабый, не нагружаем его
_LOCK = asyncio.Lock()


async def build_plan() -> dict | None:
    """Что куда переедет. None — сайт не ответил."""
    cats = await wp.all_categories()
    posts = await wp.all_posts("id,categories,tags,link")
    if cats is None or posts is None:
        return None
    by_id = {int(c["id"]): c for c in cats}
    roots = [c for c in cats if not c.get("parent") and c["name"].casefold() == NEWS_NAME.casefold()]
    # Если рубрик «Новости» в корне несколько — берём ту, у которой есть подрубрики
    roots.sort(key=lambda c: -sum(1 for x in cats if x.get("parent") == c["id"]))
    news = roots[0] if roots else None
    children = {int(c["id"]): c["name"] for c in cats if news and c.get("parent") == news["id"]}

    moves: list[dict] = []
    unsorted = 0
    for p in posts:
        post_cats = [int(c) for c in p.get("categories") or []]
        names = [by_id.get(c, {}).get("name", "").casefold() for c in post_cats]
        if not post_cats or all(n in ("uncategorized", "без рубрики") for n in names):
            unsorted += 1
        topics = [children[c] for c in post_cats if c in children]
        if not topics or news is None:
            continue
        new_cats = [c for c in post_cats if c not in children]
        if news["id"] not in new_cats:
            new_cats.append(news["id"])
        moves.append({"id": int(p["id"]), "categories": new_cats, "topics": topics,
                      "tags": [int(t) for t in p.get("tags") or []]})
    return {
        "news": news,
        "rename": bool(news and news["name"] != NEWS_NAME),
        "moves": moves,
        "by_topic": Counter(t for m in moves for t in m["topics"]),
        "unsorted": unsorted,
        "total": len(posts),
    }


def plan_text(plan: dict) -> str:
    if plan["news"] is None:
        return f"⚠️ На сайте нет рубрики «{NEWS_NAME}» — переносить некуда."
    lines = [f"🗂 <b>Рубрики сайта</b>: всего записей {plan['total']}."]
    if plan["moves"]:
        lines.append(f"\nПереедут в рубрику «{NEWS_NAME}»: <b>{len(plan['moves'])}</b> записей. "
                     "Тема останется меткой:")
        lines += [f"• {html.escape(t)} — {n}" for t, n in plan["by_topic"].most_common()]
    else:
        lines.append(f"\nВсе новости уже в одной рубрике «{NEWS_NAME}», переносить нечего.")
    if plan["rename"]:
        lines.append(f"\nРубрика «{html.escape(plan['news']['name'])}» будет переименована в «{NEWS_NAME}» "
                     "(адрес страницы рубрики не меняется).")
    if plan["unsorted"]:
        lines.append(f"\n⚠️ Без рубрики: {plan['unsorted']} записей — их бот не трогает, "
                     "разложите их в админке WordPress.")
    lines.append("\nАдреса самих записей не меняются. Подрубрики не удаляются.")
    return "\n".join(lines)


async def apply_plan(plan: dict, progress=None) -> tuple[int, int]:
    """Переносит записи. Возвращает (перенесено, ошибок)."""
    tag_ids: dict[str, int | None] = {}
    for topic in plan["by_topic"]:
        tag_ids[topic] = await wp.ensure_tag(topic)
    ok = failed = 0
    for i, move in enumerate(plan["moves"], 1):
        tags = list(move["tags"])
        for topic in move["topics"]:
            tid = tag_ids.get(topic)
            if tid and tid not in tags:
                tags.append(tid)
        if await wp.set_post_terms(move["id"], move["categories"], tags):
            ok += 1
        else:
            failed += 1
            log.warning("Рубрики: не перенесена запись %s", move["id"])
        if progress and i % 50 == 0:
            await progress(i, len(plan["moves"]))
        await asyncio.sleep(PAUSE_SECONDS)
    if plan["rename"] and not await wp.rename_category(plan["news"]["id"], NEWS_NAME):
        failed += 1
    if ok:
        await wp.refresh_site("/news/")  # сбросить кэш страниц сайта
    return ok, failed


router = Router()
ADMIN = F.from_user.id.in_(config.ADMIN_IDS)
_APPLY = "wprub:apply"


@router.message(Command("wp_rubrics"), F.chat.type == ChatType.PRIVATE, ADMIN)
async def wp_rubrics(message: Message) -> None:
    if not wp.wp_enabled():
        await message.answer("Сайт не подключён: нужны WP_URL, WP_USER и WP_APP_PASSWORD.")
        return
    await message.answer("Смотрю записи и рубрики сайта…")
    plan = await build_plan()
    if plan is None:
        await message.answer("⚠️ Сайт не ответил, попробуйте позже.")
        return
    markup = None
    if plan["moves"] or plan["rename"]:
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Перенести", callback_data=_APPLY)]])
    await message.answer(plan_text(plan), parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data == _APPLY, ADMIN)
async def wp_rubrics_apply(callback: CallbackQuery) -> None:
    if _LOCK.locked():
        await callback.answer("Перенос уже идёт.")
        return
    await callback.answer("Запускаю перенос…")
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001 — кнопки могли уже исчезнуть
            pass
    asyncio.create_task(_run_apply(callback.bot, callback.from_user.id))


async def _run_apply(bot, chat_id: int) -> None:
    async with _LOCK:
        try:
            plan = await build_plan()  # заново: между отчётом и кнопкой могли выйти новые записи
            if plan is None:
                await bot.send_message(chat_id, "⚠️ Сайт не ответил, перенос не начат.")
                return

            async def progress(done: int, total: int) -> None:
                await bot.send_message(chat_id, f"Перенесено {done} из {total}…")

            ok, failed = await apply_plan(plan, progress)
            text = f"✅ Готово: перенесено {ok} записей в «{NEWS_NAME}»."
            if failed:
                text += f"\n⚠️ Не получилось: {failed}. Повторите /wp_rubrics — бот перенесёт оставшиеся."
            await bot.send_message(chat_id, text)
        except Exception as e:  # noqa: BLE001
            log.exception("Рубрики: ошибка переноса: %s", e)
            await bot.send_message(chat_id, f"⚠️ Перенос остановлен: {type(e).__name__}: {e}")
