"""Раздел «📚 Полезное» — справочник о жизни в Нидерландах.

Краткие выжимки по ключевым темам (жильё, документы, деньги и т.д.) с
официальными ссылками. Точные суммы/правила НЕ зашиваем в текст (они меняются) —
за ними отсылаем к ИИ и официальным сайтам. Навигация — инлайн-кнопками.
"""
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from keyboards.menus import BTN_GUIDE, main_menu
from utils.analytics import log_event

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

_CTA = "\n\n💬 Нужны точные цифры или специалист (юрист, риелтор…)? Спроси меня или нажми «🔍 Найти специалиста» в меню."

# key -> (кнопка, текст гайда). Порядок задаёт вид меню.
GUIDES: dict[str, tuple[str, str]] = {
    "housing": (
        "🏠 Жильё",
        "🏠 <b>Жильё в Нидерландах</b>\n\n"
        "<b>Частная аренда (vrije sector):</b>\n"
        "• <a href=\"https://www.pararius.nl\">Pararius</a>, <a href=\"https://www.funda.nl\">Funda</a> — квартиры и дома\n"
        "• <a href=\"https://kamernet.nl\">Kamernet</a> — комнаты и студии\n"
        "• <a href=\"https://housinganywhere.com\">HousingAnywhere</a> — для экспатов, на средний срок\n"
        "• Депозит обычно 1–2 месяца. ⚠️ Никогда не платите до просмотра и договора — частая схема мошенничества.\n\n"
        "<b>Социальное жильё (sociale huur):</b>\n"
        "• Дешевле, но длинные очереди. Регистрируешься на региональных порталах (часто через "
        "<a href=\"https://www.woningnet.nl\">WoningNet</a>), копится «стаж регистрации». Есть порог дохода.\n\n"
        "<b>Обмен соц. жилья (woningruil):</b>\n"
        "• Арендаторы соц. жилья могут поменяться квартирами — оформляется через свою "
        "жилищную корпорацию (нужно согласие обеих сторон). Найти вариант для обмена: "
        "<a href=\"https://www.ruilmijnwoning.nl\">ruilmijnwoning.nl</a> или "
        "<a href=\"https://huisruilen.nl\">huisruilen.nl</a>.\n\n"
        "<b>Полезно знать:</b>\n"
        "• Прописка (inschrijving) в gemeente возможна, только если жильё это разрешает.\n"
        "• Пособие на аренду — <a href=\"https://www.toeslagen.nl\">huurtoeslag</a>.\n"
        "• Споры о завышенной цене — <a href=\"https://www.huurcommissie.nl\">Huurcommissie</a>.",
    ),
    "docs": (
        "🪪 Документы и старт",
        "🪪 <b>Документы и первые шаги после переезда</b>\n\n"
        "<b>1. Регистрация в gemeente (inschrijven)</b> — запишись на приём заранее. Нужны паспорт, "
        "договор аренды и часто переведённое/апостилированное свид. о рождении.\n"
        "<b>2. BSN</b> — выдаётся при регистрации; нужен для работы, банка, налогов, врача.\n"
        "<b>3. <a href=\"https://www.digid.nl\">DigiD</a></b> — цифровой ключ ко всем госуслугам (после BSN).\n"
        "<b>4. ВНЖ / виза</b> — всё про пермиты и продление на <a href=\"https://ind.nl\">IND</a>.\n"
        "<b>5. <a href=\"https://mijn.overheid.nl\">MijnOverheid</a></b> — личный кабинет: письма госорганов в одном месте.\n\n"
        "Официально: <a href=\"https://www.government.nl\">government.nl</a> и сайт твоего gemeente.",
    ),
    "money": (
        "💶 Деньги",
        "💶 <b>Банки, налоги и пособия</b>\n\n"
        "<b>Банк:</b> нужен BSN. Популярны ABN AMRO, ING, Rabobank; быстро онлайн — bunq, Revolut.\n\n"
        "<b>Налоги — <a href=\"https://www.belastingdienst.nl\">Belastingdienst</a>:</b> годовая декларация "
        "(aangifte) обычно с марта, вход по DigiD.\n\n"
        "<b>Пособия — <a href=\"https://www.toeslagen.nl\">Toeslagen</a></b> (зависят от дохода):\n"
        "• huurtoeslag — на аренду\n• zorgtoeslag — на медстраховку\n"
        "• kinderopvangtoeslag — на садик\n• kindgebonden budget — на детей\n\n"
        "<b>30%-ruling</b> — налоговая льгота для приехавших специалистов (оформляется через работодателя).",
    ),
    "health": (
        "🏥 Здоровье",
        "🏥 <b>Здоровье и страховка</b>\n\n"
        "• <b>Медстраховка (zorgverzekering) обязательна</b> — базовую (basisverzekering) нужно оформить "
        "в течение 4 месяцев после регистрации. Сравнить: <a href=\"https://www.independer.nl\">Independer</a>, "
        "<a href=\"https://www.zorgwijzer.nl\">Zorgwijzer</a>.\n"
        "• <b>huisarts</b> (семейный врач) — точка входа во всю медицину. Зарегистрируйся рядом с домом.\n"
        "• <b>Экстренно — 112.</b> Не срочно, но вне часов приёма — huisartsenpost.\n"
        "• Лекарства — в аптеке (apotheek), многие по рецепту.\n"
        "• Пособие на страховку — <a href=\"https://www.toeslagen.nl\">zorgtoeslag</a>.",
    ),
    "transport": (
        "🚲 Транспорт",
        "🚲 <b>Транспорт</b>\n\n"
        "• <b>Оплата проезда:</b> OVpay (обычной банковской картой) или OV-chipkaart — поезд, трамвай, автобус, метро.\n"
        "• <b>Поезда — <a href=\"https://www.ns.nl\">NS</a></b>; маршруты по всем видам транспорта — <a href=\"https://9292.nl\">9292</a>.\n"
        "• <b>Велосипед</b> — главный транспорт. Б/у часто берут на Marktplaats; нужен хороший замок и страховка от угона.\n"
        "• <b>Права:</b> обмен иностранных прав — <a href=\"https://www.rdw.nl\">RDW</a> (для 30%-ruling часто без экзамена); "
        "иначе экзамен через <a href=\"https://www.cbr.nl\">CBR</a>.",
    ),
    "work": (
        "💼 Работа",
        "💼 <b>Работа</b>\n\n"
        "• <b>Поиск:</b> Indeed, LinkedIn, <a href=\"https://undutchables.nl\">Undutchables</a> (для экспатов), "
        "<a href=\"https://www.werk.nl\">werk.nl</a> (UWV).\n"
        "• Для работы нужен BSN. Контракт бывает срочный (tijdelijk) и бессрочный (vast); зарплатный лист — loonstrook.\n"
        "• Обычно есть отпускные (vakantiegeld, ~8%).\n"
        "• Потеря работы — пособие WW через <a href=\"https://www.uwv.nl\">UWV</a>.\n"
        "• Бесплатная юр. помощь по трудовым спорам — <a href=\"https://www.juridischloket.nl\">Juridisch Loket</a>.",
    ),
    "kids": (
        "👶 Дети и школа",
        "👶 <b>Дети и школа</b>\n\n"
        "• Зарегистрируй ребёнка в gemeente — ему тоже дадут BSN.\n"
        "• <b>Садик (kinderopvang)</b> — частично компенсируется через "
        "<a href=\"https://www.toeslagen.nl\">kinderopvangtoeslag</a>.\n"
        "• <b>Школа</b> обязательна с 5 лет (leerplicht); запись напрямую в выбранную школу.\n"
        "• <b>Детские выплаты:</b> kinderbijslag через <a href=\"https://www.svb.nl\">SVB</a> + kindgebonden budget.\n"
        "• <b>Consultatiebureau</b> — бесплатный патронаж и прививки для малышей.",
    ),
}

_INTRO = (
    "📚 <b>Полезное о жизни в Нидерландах</b>\n\n"
    "Выбери тему — дам краткую выжимку с официальными ссылками. "
    "А за точными цифрами и под свою ситуацию — просто спроси меня 💬"
)


def _menu_kb() -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(text=label, callback_data=f"g:{key}")
            for key, (label, _) in GUIDES.items()]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _guide_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ К темам", callback_data="g:menu")]]
    )


@router.message(Command("guide", "info"))
@router.message(F.text == BTN_GUIDE)
async def show_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await log_event("guide", "menu")
    await message.answer(_INTRO, reply_markup=_menu_kb(), disable_web_page_preview=True)


@router.callback_query(F.data == "g:menu")
async def back_to_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(_INTRO, reply_markup=_menu_kb(), disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data.startswith("g:"))
async def show_guide(callback: CallbackQuery) -> None:
    key = callback.data.split(":", 1)[1]
    guide = GUIDES.get(key)
    if not guide:
        await callback.answer()
        return
    await log_event("guide", key)
    await callback.message.edit_text(
        guide[1] + _CTA, reply_markup=_guide_kb(), disable_web_page_preview=True
    )
    await callback.answer()
