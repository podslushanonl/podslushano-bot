"""Поиск специалиста по гайду контактов (умный поиск по базе).

Бот ведёт живой диалог: если человек написал только профессию — спросит город
(и запомнит, кого ищем); если только город — спросит, кто нужен.
"""
import html
import random
import re
from datetime import datetime

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, or_, select

import config
from database.db import get_session
from database.models import Specialist
from keyboards.menus import BTN_CONTACTS, BTN_SELF_ADD, cancel_menu, feedback_kb, main_menu
from states.forms import ContactSearch, ReviewForm
from utils.ai import extract_specialist_query, reply_with_ai
from utils.analytics import log_event
from utils.contact_links import TELEGRAM_TYPES, parse_contact_links
from utils.reviews import (
    add_or_update_review,
    rating_badge,
    ratings_for,
    set_review_text,
    specialist_key,
    texts_for,
)
from utils.geo import CATEGORIES, NEIGHBORS, detect_category, detect_city

router = Router()
# Поиск специалистов — только в личных чатах
router.message.filter(F.chat.type == ChatType.PRIVATE)

FOUND_PHRASES = [
    "Отличные новости — нашёл! 🎉",
    "Есть такой человек! 😎",
    "Нашёл, держи 👌",
]

# Глаголы-процессы: «как ЗАПИСАТЬСЯ к huisarts», «как ОФОРМИТЬ zorgtoeslag»,
# «как ОТКРЫТЬ bankrekening». Связка «как» + такой глагол = просьба объяснить
# процесс (на неё отвечает ИИ по официальным источникам), а НЕ поиск человека
# в гайде. Это важно: иначе «huisarts» ловится как профессия «врач» и бот зря
# спрашивает город вместо инструкции.
_HOWTO_VERBS = (
    "записаться", "записать", "запис", "оформить", "оформля", "открыть",
    "получить", "сделать", "подать", "регистр", "прописат", "продлить",
    "поменять", "сменить", "оплатить", "заплатить", "вернуть", "арендовать",
    "снять", "застраховать", "перевести", "подключить", "закрыть",
    "расторгнуть", "обжаловать", "заполнить", "обменять", "встать на",
)


def is_howto_question(text: str) -> bool:
    """True, если это вопрос «как сделать X» — инструкция, а не поиск специалиста.

    Требуем отдельное слово «как» (а не «какой/какая») рядом с глаголом-процессом,
    чтобы обычные запросы вроде «нужен huisarts в Амстердаме» по-прежнему вели
    в поиск по гайду.
    """
    low = (text or "").lower()
    if not re.search(r"\bкак\b", low):
        return False
    return any(v in low for v in _HOWTO_VERBS)


# Эмодзи для красивых кнопок категорий
CATEGORY_EMOJI = {
    "стоматолог": "🦷", "врач": "🩺", "психолог": "🧠", "юрист": "⚖️", "бухгалтер": "📊",
    "риелтор": "🏠", "репетитор": "📚", "музыка": "🎵", "парикмахер": "💇", "мастер маникюра": "💅",
    "косметолог": "✨", "массаж": "💆", "тату": "🖋", "фотограф": "📷", "дизайнер": "🎨",
    "ремонт": "🔧", "мастер на час": "🛠", "клининг": "🧹", "кондитер": "🧁", "еда": "🍽",
    "няня": "🍼", "аниматор": "🎈", "фитнес": "🏋", "гид": "🗺", "ведущий": "🎤", "стилист": "👗",
    "автошкола": "🚗", "веб-разработчик": "💻", "творчество": "🎭", "автосервис": "🚙",
    "нутрициолог": "🥗", "услуги": "🧩",
}
POPULAR_CITIES = ["Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Eindhoven", "Groningen"]


async def _active_category_counts() -> dict[str, int]:
    """Сколько активных специалистов в каждой категории."""
    now = datetime.utcnow()
    async with get_session() as session:
        rows = (
            await session.execute(
                select(Specialist.category, func.count())
                .where(
                    Specialist.status == "active",
                    or_(Specialist.paid_until.is_(None), Specialist.paid_until > now),
                )
                .group_by(Specialist.category)
            )
        ).all()
    return {cat: n for cat, n in rows}


def _categories_kb(counts: dict[str, int]) -> InlineKeyboardMarkup:
    # Показываем популярные категории (≥2 специалистов), по убыванию количества.
    cats = [c for c, n in sorted(counts.items(), key=lambda x: -x[1]) if n >= 2]
    btns = [
        InlineKeyboardButton(text=f"{CATEGORY_EMOJI.get(c, '•')} {c}", callback_data=f"fcat|{c}")
        for c in cats
    ]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cities_kb(cat: str) -> InlineKeyboardMarkup:
    # Категорию зашиваем прямо в кнопку — не зависим от состояния диалога.
    btns = [InlineKeyboardButton(text=c, callback_data=f"fcity|{cat}|{c}") for c in POPULAR_CITIES]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton(text="🌍 Показать всех (вся страна)", callback_data=f"fcity|{cat}|__all__")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == BTN_CONTACTS)
async def ask_query(message: Message, state: FSMContext) -> None:
    await state.set_state(ContactSearch.waiting_for_query)
    counts = await _active_category_counts()
    await message.answer(
        "Кого ищем? Напиши словами — например «стоматолог в Амстердаме» — "
        "или выбери категорию ниже 👇",
        reply_markup=cancel_menu(),
    )
    await message.answer(
        "📂 Популярные категории (или просто напиши, кого ищешь):",
        reply_markup=_categories_kb(counts),
    )


@router.callback_query(F.data.startswith("fcat|"))
async def pick_category(callback: CallbackQuery, state: FSMContext) -> None:
    cat = callback.data.split("|", 1)[1]
    await state.set_state(ContactSearch.waiting_for_query)
    await state.update_data(pending_category=cat, pending_terms=[])
    await callback.message.answer(
        f"Ищем «{cat}» 👌 В каком городе? Напиши город или выбери 👇",
        reply_markup=cancel_menu(),
    )
    await callback.message.answer("📍 Города:", reply_markup=_cities_kb(cat))
    await callback.answer()


@router.callback_query(F.data.startswith("fcity|"))
async def pick_city(callback: CallbackQuery, state: FSMContext) -> None:
    _, cat, val = callback.data.split("|", 2)
    await state.set_state(ContactSearch.waiting_for_query)
    await state.update_data(pending_category=cat, pending_terms=[])
    if val == "__all__":
        await log_event("search", cat)
        now = datetime.utcnow()
        async with get_session() as session:
            allspecs = (
                await session.scalars(
                    select(Specialist).where(
                        Specialist.category == cat,
                        Specialist.status == "active",
                        or_(Specialist.paid_until.is_(None), Specialist.paid_until > now),
                    )
                )
            ).all()
        if allspecs:
            # локальные сгруппированы, онлайн — в конце
            allspecs = sorted(allspecs, key=lambda s: (s.is_online, s.province or "", s.city or ""))
            await _send_results(
                callback.message, state,
                [(f"Специалисты «{cat}» по всей стране:", allspecs)],
            )
        else:
            await state.clear()
            await callback.message.answer(
                "Пока пусто в этой категории 🙂", reply_markup=main_menu()
            )
        await callback.answer()
        return
    await process_query(callback.message, state, val)
    await callback.answer()


MAX_RESULTS = 8  # максимум карточек в одной выдаче (каждая — отдельным сообщением)

# Слова, которые не несут смысла для ранжирования
_STOP = {
    "нужен", "нужна", "нужно", "ищу", "ищем", "найти", "найди", "найдите",
    "посоветуй", "посоветуйте", "порекомендуй", "хочу", "мне", "для", "есть",
    "как", "где", "который", "хороший", "хорошего", "лучший", "срочно", "можно",
    "пожалуйста", "специалист", "специалиста", "контакт", "контакты",
}


def _query_tokens(text: str) -> list[str]:
    """Значимые слова из запроса (без городов, предлогов и т.п.) — для релевантности."""
    tokens = []
    for w in re.findall(r"[а-яёa-z]{4,}", (text or "").lower()):
        if w in _STOP or detect_city(w):
            continue
        tokens.append(w)
    return tokens


def _filter_relevant(specs: list, tokens: list[str]) -> list:
    """Оставляет специалистов, чьё имя/описание совпадают с запросом, ранжируя по совпадениям.

    Если конкретных слов нет или ничего не совпало — возвращает список как есть.
    """
    if not tokens:
        return specs
    scored = []
    for s in specs:
        hay = f"{s.name} {s.description or ''} {s.category}".lower()
        score = sum(1 for t in tokens if t[:5] in hay)
        scored.append((score, s))
    if any(score > 0 for score, _ in scored):
        return [s for score, s in sorted(scored, key=lambda x: -x[0]) if score > 0]
    return specs


def _spec_text(spec: Specialist, badge: str = "",
               reviews: list[tuple[int, str]] | None = None) -> str:
    """Текст карточки одного специалиста (данные экранируем для HTML)."""
    where = "онлайн" if spec.is_online else (spec.city or spec.province)
    text = "🌟 " if spec.is_premium else ""
    text += f"<b>{html.escape(spec.name)}</b>"
    if where:
        text += f" · {html.escape(where)}"
    if badge:
        text += f"  {badge}"
    if spec.description:
        text += f"\n{html.escape(spec.description)}"
    if spec.contact:
        text += f"\n📞 {html.escape(spec.contact)}"
    for rating, rtext in reviews or []:
        text += f"\n\n💬 {'⭐' * rating}\n<i>«{html.escape(rtext)}»</i>"
    return text


def _spec_card_kb(spec: Specialist, idx: int, total: int) -> InlineKeyboardMarkup:
    """Карточка специалиста: кнопки-ссылки + «Оценить» + навигация ◀️ N/M ▶️."""
    links = [l for l in parse_contact_links(spec.contact) if l["type"] in TELEGRAM_TYPES]
    btns = [InlineKeyboardButton(text=l["label"], url=l["url"]) for l in links]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton(text="⭐ Оценить", callback_data=f"rate:{spec.id}")])
    if total > 1:
        prev, nxt = (idx - 1) % total, (idx + 1) % total
        rows.append([
            InlineKeyboardButton(text="◀️", callback_data=f"spv:{prev}"),
            InlineKeyboardButton(text=f"{idx + 1}/{total}", callback_data="spv_noop"),
            InlineKeyboardButton(text="▶️", callback_data=f"spv:{nxt}"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _spec_show(msg: Message, state: FSMContext, idx: int, replace: bool) -> None:
    """Показывает одну карточку специалиста из сохранённого списка (карусель).

    replace=True — листание: удаляем старую карточку и шлём новую (так корректно
    работает и для фото-карточек премиума, и для обычных текстовых).
    """
    data = await state.get_data()
    ids = data.get("sp_ids") or []
    labels = data.get("sp_labels") or []
    if not ids:
        await msg.answer("Список устарел — поищи заново 🙂", reply_markup=main_menu())
        return
    idx %= len(ids)
    async with get_session() as session:
        spec = await session.get(Specialist, ids[idx])
    if spec is None:
        await msg.answer("Эта карточка пропала — поищи заново 🙂", reply_markup=main_menu())
        return
    key = specialist_key(spec.name, spec.contact)
    badge = rating_badge((await ratings_for([key])).get(key))
    revs = (await texts_for([key])).get(key)
    header = labels[idx] if idx < len(labels) else ""
    text = (f"{header}\n\n" if header else "") + _spec_text(spec, badge, revs)
    kb = _spec_card_kb(spec, idx, len(ids))
    chat_id, bot = msg.chat.id, msg.bot
    if replace:
        try:
            await msg.delete()
        except Exception:  # noqa: BLE001 — старое сообщение могло исчезнуть
            pass
    if spec.photo_file_id and len(text) <= 1024:
        try:
            await bot.send_photo(chat_id, spec.photo_file_id, caption=text, reply_markup=kb)
            return
        except Exception:  # noqa: BLE001 — фото недоступно → текстом
            pass
    await bot.send_message(chat_id, text, reply_markup=kb, disable_web_page_preview=True)


async def _send_results(message: Message, state: FSMContext, sections: list) -> None:
    """Складывает результаты в карусель: одна карточка за раз с навигацией ◀️ ▶️."""
    await state.clear()
    seen: set[tuple[str, str]] = set()
    ids: list[int] = []
    labels: list[str] = []
    overflow = 0
    for header, specs in sections:
        uniq = []
        for s in specs:
            key = (s.name.strip().lower(), (s.contact or "").strip().lower())
            if key in seen:
                continue
            seen.add(key)
            uniq.append(s)
        uniq.sort(key=lambda s: 0 if s.is_premium else 1)  # премиум — вперёд
        for s in uniq:
            if len(ids) >= MAX_RESULTS:
                overflow += 1
                continue
            ids.append(s.id)
            labels.append(header)
    if not ids:
        await message.answer(
            "К сожалению, по этому запросу у нас пока никого нет в гайде 😔\n\n"
            f"Попробуйте другой город или направление. А ещё можно добавить себя или "
            f"знакомого специалиста — кнопка «{BTN_SELF_ADD}» или /selfadd 🙌",
            reply_markup=main_menu(),
        )
        return
    await state.update_data(sp_ids=ids, sp_labels=labels)
    note = f" (показываю первых {len(ids)} — уточни город, найду ближе)" if overflow else ""
    await message.answer(
        f"🔍 Нашёл подходящих: <b>{len(ids)}</b>{note}.\n"
        "Листай карточки кнопками ◀️ ▶️ под карточкой 👇",
        reply_markup=main_menu(),
    )
    await _spec_show(message, state, 0, replace=False)


@router.callback_query(F.data.startswith("spv:"))
async def spec_nav(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        idx = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer()
        return
    await callback.answer()
    await _spec_show(callback.message, state, idx, replace=True)


@router.callback_query(F.data == "spv_noop")
async def spec_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(ContactSearch.waiting_for_query)
async def receive_query(message: Message, state: FSMContext) -> None:
    await process_query(message, state, message.text or "")


# Слова, которые сами по себе не означают «направление» (служебные/городские)
_SEARCH_STOPWORDS = {
    "ищу", "ищем", "нужен", "нужна", "нужно", "найти", "поиск", "рядом", "около",
    "город", "городе", "районе", "район", "центр", "centre", "center", "пожалуйста",
    "можно", "есть", "хочу", "мне", "нам", "для", "это", "что", "кто", "где",
}


def _extra_terms(text: str, city: str, province: str | None) -> list[str]:
    """Слова-направления из запроса, помимо города/служебных слов.

    «грумер в Гааге» → ['грумер']; просто «Гаага» → []."""
    place = f"{city} {province or ''}".lower()
    out: list[str] = []
    for w in re.findall(r"[а-яёa-z]+", text.lower()):
        if len(w) < 4 or w in _SEARCH_STOPWORDS:
            continue
        # отбрасываем слова, похожие на название города/провинции (с учётом склонений)
        if w in place or w[:4] in place:
            continue
        out.append(w)
    return out


def _names_unknown_profession(text: str, city: str, province: str | None) -> bool:
    """True, если в тексте есть слово-направление, помимо города/служебных слов.

    Помогает отличить «грумер в Гааге» (названо направление, которого нет в
    гайде) от просто «Гаага» (нужно спросить, кто нужен)."""
    return bool(_extra_terms(text, city, province))


async def process_query(message: Message, state: FSMContext, text: str) -> None:
    """Разбирает запрос и ищет специалиста. Вызывается и из свободного чата.

    Помнит контекст между сообщениями: если бот уже спросил «в каком городе?»,
    то следующее сообщение («в Гааге») продолжит тот же поиск.
    """
    data = await state.get_data()

    # «Как записаться к huisarts», «как оформить zorgtoeslag» — это просьба
    # объяснить процесс. Отдаём ИИ (он ответит по официальным источникам), а не
    # уводим в поиск специалиста. Не перехватываем, если уже уточняем активный
    # поиск (пользователь внутри диалога «кого ищем / в каком городе»).
    if (
        is_howto_question(text)
        and not data.get("pending_category")
        and not data.get("pending_province")
        and await reply_with_ai(message, state)
    ):
        return

    category = detect_category(text) or data.get("pending_category")
    city_info = detect_city(text)
    # Город мог прийти прошлым сообщением (уже разобранный)
    if not city_info and data.get("pending_province"):
        city_info = (data.get("pending_city") or data["pending_province"], data["pending_province"])

    # Если ключевые слова не дали категорию ИЛИ город — спросим ИИ. Он понимает
    # синонимы/опечатки и знает провинцию даже для маленьких городов (Oisterwijk).
    if not category or not city_info:
        extracted = await extract_specialist_query(
            text, list(CATEGORIES.keys()), list(NEIGHBORS.keys())
        )
        if not category and extracted.get("category"):
            category = extracted["category"]
        if not city_info:
            known = detect_city(extracted["city"]) if extracted.get("city") else None
            if known:
                city_info = known
            elif extracted.get("province"):
                city_info = (extracted.get("city") or extracted["province"], extracted["province"])

    # Совсем не про специалиста — передаём ИИ и выходим из режима поиска
    if not category and not city_info:
        if await reply_with_ai(message, state):
            return
        categories = ", ".join(CATEGORIES.keys())
        await state.set_state(ContactSearch.waiting_for_query)
        await message.answer(
            "Хм, я не совсем понял, кто нужен 🤔 Я ищу по категориям: "
            f"{categories}.\n\n"
            "Напиши, например: <i>«юрист в Роттердаме»</i> — и я поищу.",
            reply_markup=feedback_kb(),
        )
        return

    # Город есть, а категорию не распознали
    if not category:
        city, province = city_info
        # Пользователь уже называл направление (есть слово кроме города) ИЛИ мы уже
        # спрашивали «кто нужен?» — значит такого направления просто нет в гайде.
        asked_before = bool(data.get("pending_province"))
        if asked_before or _names_unknown_profession(text, city, province):
            # Фиксируем спрос на направление, которого нет в нашем списке категорий
            term = " ".join(_extra_terms(text, city, province)) or text.strip().lower()
            if term:
                await log_event("search_miss", term[:80])
            await state.clear()
            await message.answer(
                f"К сожалению, по запросу «{html.escape(text.strip()[:80])}» в городе "
                f"{html.escape(city)} у нас пока никого нет в гайде 😔\n\n"
                f"Можно добавить себя или знакомого специалиста — кнопка «{BTN_SELF_ADD}» "
                "или /selfadd. Или попробуйте другое направление либо город 🙂",
                reply_markup=main_menu(),
            )
            return
        # В сообщении был только город — спросим, кто нужен
        await state.set_state(ContactSearch.waiting_for_query)
        await state.update_data(pending_city=city, pending_province=province)
        await message.answer(
            f"Так, город понял — {city} 📍 А кто нужен? "
            "Например: стоматолог, юрист, парикмахер…",
            reply_markup=cancel_menu(),
        )
        return

    # Кто нужен — понятно, города нет
    if not city_info:
        await state.set_state(ContactSearch.waiting_for_query)
        await state.update_data(pending_category=category, pending_terms=_query_tokens(text))
        await message.answer(
            f"Понял, ищем — <b>{category}</b> 👌 В каком городе ты находишься?",
            reply_markup=feedback_kb(),
        )
        return

    city, province = city_info
    neighbor_provinces = NEIGHBORS.get(province, [])
    await log_event("search", category)

    now = datetime.utcnow()
    async with get_session() as session:
        async def fetch(*conds):
            result = await session.scalars(
                select(Specialist).where(
                    Specialist.category == category,
                    Specialist.status == "active",
                    # бессрочные (seed/admin) или ещё оплаченные
                    or_(Specialist.paid_until.is_(None), Specialist.paid_until > now),
                    *conds,
                )
            )
            return result.all()

        online = await fetch(Specialist.is_online.is_(True))
        in_province = await fetch(
            Specialist.is_online.is_(False), Specialist.province == province
        )
        in_neighbors = (
            await fetch(
                Specialist.is_online.is_(False),
                Specialist.province.in_(neighbor_provinces),
            )
            if neighbor_provinces
            else []
        )

    # Релевантность: если в запросе были конкретные слова («вокал», «детский»…),
    # показываем только подходящих, а не всю широкую категорию.
    terms = _query_tokens(text)
    if data.get("pending_terms"):
        terms = list(dict.fromkeys(terms + data["pending_terms"]))

    def _has_term_match(specs: list) -> bool:
        return any(
            any(t[:5] in f"{s.name} {s.description or ''} {s.category}".lower() for t in terms)
            for s in specs
        )

    # «Широкое» совпадение: назвали конкретику (напр. «лазерная эпиляция»), но
    # точно никто не подходит — покажем профиль категории, но честно об этом скажем.
    loose = bool(terms) and not _has_term_match(online + in_province + in_neighbors)

    online = _filter_relevant(online, terms)
    in_province = _filter_relevant(in_province, terms)
    in_neighbors = _filter_relevant(in_neighbors, terms)

    # Премиум — вперёд, затем точные совпадения по городу
    in_province = sorted(
        in_province,
        key=lambda s: (0 if s.is_premium else 1, 0 if (city and s.city == city) else 1),
    )
    has_exact_city = any(city and s.city == city for s in in_province)

    # Честный вводный заголовок: «нашёл!» только при точном совпадении; иначе —
    # «точного нет, вот профиль рядом».
    lead = (
        "Точного мастера именно под ваш запрос не нашёл 🙏 Но вот специалисты "
        "этого профиля — у них можно уточнить 👇"
        if loose else random.choice(FOUND_PHRASES)
    )

    sections: list = []
    if in_province:
        if has_exact_city:
            loc = f"Вот кто есть в {city} и рядом ({province}):"
        elif city.strip().lower() == province.strip().lower():
            loc = f"Вот специалисты в провинции {province}:"
        else:
            loc = (
                f"В самом {city} точных совпадений нет, "
                f"но вот кто работает рядом — в провинции {province}:"
            )
        sections.append((f"{lead}\n{loc}", in_province))
    elif in_neighbors:
        sections.append(
            (f"{lead}\nБлижайшие к {city} — в соседних провинциях:", in_neighbors)
        )

    if online:
        if sections:
            sections.append(("🌐 А ещё работают онлайн (по всей стране):", online))
        else:
            sections.append(
                (f"{lead}\nРаботают по всей стране — а значит, и в {city}:", online)
            )

    if sections:
        await _send_results(message, state, sections)
        return

    # Совсем ничего не нашли — предлагаем гайд на сайте
    fallback = (
        f"Эх, рядом с {city} по такому запросу в моей базе пока "
        "пусто 😔 Но база пополняется!"
    )
    if config.GUIDE_URL:
        fallback += f"\n\nЗагляни в полный гайд на нашем сайте: {config.GUIDE_URL}"
    fallback += "\n\nИ попробуй спросить позже — вдруг появится 😉"
    await _finish(message, state, fallback)


async def _finish(message: Message, state: FSMContext, text: str) -> None:
    """Отправляет результат и возвращает в главное меню."""
    await state.clear()
    await message.answer(text, reply_markup=main_menu(), disable_web_page_preview=True)


# --- Отзывы и рейтинг -------------------------------------------------------

def _stars_kb(spec_id: int) -> InlineKeyboardMarkup:
    btns = [
        InlineKeyboardButton(text=f"{n}⭐", callback_data=f"rstar:{spec_id}:{n}")
        for n in range(1, 6)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[btns])


@router.callback_query(F.data.startswith("rate:"))
async def rate_open(callback: CallbackQuery) -> None:
    spec_id = int(callback.data.split(":", 1)[1])
    await callback.message.answer("Оцени специалиста 👇", reply_markup=_stars_kb(spec_id))
    await callback.answer()


@router.callback_query(F.data.startswith("rstar:"))
async def rate_set(callback: CallbackQuery, state: FSMContext) -> None:
    _, sid, n = callback.data.split(":")
    rating = int(n)
    async with get_session() as session:
        sp = await session.get(Specialist, int(sid))
    if sp is None:
        await callback.answer("Карточка не найдена — попробуй поиск заново", show_alert=True)
        return
    key = specialist_key(sp.name, sp.contact)
    await add_or_update_review(key, callback.from_user.id, rating, None)
    await state.set_state(ReviewForm.waiting_text)
    await state.update_data(review_key=key)
    await callback.message.answer(
        f"Спасибо за оценку {rating}⭐! Хочешь добавить пару слов об опыте? "
        "Напиши отзыв или нажми «Пропустить».",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Пропустить", callback_data="rskip")]]
        ),
    )
    await callback.answer("Оценка сохранена ⭐")


@router.callback_query(F.data == "rskip")
async def rate_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Готово, спасибо! 🙌", reply_markup=main_menu())
    await callback.answer()


@router.message(ReviewForm.waiting_text)
async def rate_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    key = data.get("review_key")
    if key and message.text:
        await set_review_text(key, message.from_user.id, message.text.strip())
    await state.clear()
    await message.answer("Спасибо за отзыв! 🙌", reply_markup=main_menu())
