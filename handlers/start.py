"""Команда /start и показ главного меню."""
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import config
from keyboards.menus import BTN_CANCEL, BTN_STICKERS, main_menu, stickers_button

router = Router()
# Всё «личное» меню работает только в личных чатах, не в группах
router.message.filter(F.chat.type == ChatType.PRIVATE)

WELCOME_SHORT = (
    "Привет, {name}! 👋 Я — бот сообщества «Подслушано в Нидерландах» 🇳🇱\n\n"
    "💬 <b>Самое простое — просто напиши мне любой вопрос о жизни в NL.</b>\n"
    "BSN, DigiD, налоги, жильё, врачи, транспорт, ВНЖ — отвечу по делу и при "
    "необходимости загляну в свежие официальные источники.\n"
    "<i>Например: «Как получить DigiD?» или «Положена ли мне zorgtoeslag?»</i>\n\n"
    "А ещё через меню можно 👇\n"
    "📩 прислать фото непонятного письма (Belastingdienst, gemeente…) — объясню по-русски\n"
    "📚 открыть «Полезное» — гайды о жизни в NL (жильё, документы, деньги…)\n"
    "🔍 найти специалиста из проверенного гайда\n"
    "📰 прислать историю анонимно · ❓ задать вопрос сообществу\n"
    "🎬 прислать видео · 📢 реклама и сотрудничество\n\n"
    "Просто напиши или выбери пункт меню. Подробнее — /help 🙂"
)

WELCOME = (
    "Привет, {name}! 👋\n\n"
    "Я — голос «Подслушано в Нидерландах», твой помощник по жизни в NL 🇳🇱 "
    "Помогу разобраться с бытом, найти нужных людей и поделиться своим.\n\n"
    "<b>Вот что я умею</b> 👇\n\n"
    "📰 <b>История / сплетня</b>\n"
    "Расскажи что-то интересное из жизни в Нидерландах — опубликуем "
    "<b>анонимно</b> в нашем Instagram.\n"
    "<i>Например: «В Albert Heijn кассир заговорил со мной по-русски 😄»</i>\n\n"
    "❓ <b>Вопрос сообществу</b>\n"
    "Спроси совета или опыта у наших подписчиков — отправим в предложку, "
    "ответят живые люди.\n"
    "<i>Например: «Кто сталкивался: отработал, а зарплату не выплатили — "
    "куда обращаться?»</i>\n\n"
    "🎬 <b>Видео</b>\n"
    "Снимаешь контент о жизни в NL? Пришли ролик — можем опубликовать у себя.\n"
    "<i>Например: рилс «5 лайфхаков для новичка в Нидерландах»</i>\n\n"
    "📢 <b>Реклама / сотрудничество</b>\n"
    "Хочешь рассказать о своём деле нашей аудитории? Оставь заявку — обсудим.\n"
    "<i>Например: «Реклама салона красоты в Роттердаме»</i>\n\n"
    "🔍 <b>Найти специалиста</b>\n"
    "Подберу контакт из проверенного гайда — врачи, юристы, мастера и другие.\n"
    "<i>Например: «Нужен стоматолог в Амстердаме»</i>\n\n"
    "💬 А ещё можно <b>просто спросить меня о жизни в Нидерландах</b> — отвечу "
    "по делу и при необходимости загляну в интернет за свежими данными.\n"
    "<i>Например: «Как получить DigiD?» или «Сколько сейчас стоит продление ВНЖ?»</i>"
)


def _footer() -> str:
    return (
        f"\n\n🌐 Сайт: {config.SITE_URL}\n"
        "✉️ Связаться с нами (вопросы, возвраты): /contact\n"
        "📄 /privacy — конфиденциальность и условия"
    )


def welcome_text(name: str) -> str:
    """Короткое приветствие для /start — с акцентом «просто напиши вопрос»."""
    text = WELCOME_SHORT.format(name=name)
    if config.payments_enabled():
        text += "\n\n➕ Специалист или бизнес? Размести себя в гайде — кнопка в меню."
    return text + _footer()


def features_text(name: str) -> str:
    """Подробный список возможностей — для /help."""
    text = WELCOME.format(name=name)
    if config.payments_enabled():
        text += (
            "\n\n➕ <b>Добавить себя в гайд</b>\n"
            "Специалист или бизнес? Размести свою карточку, чтобы тебя находили.\n"
            "<i>Например: мастер маникюра, юрист, фотограф…</i>"
        )
    return text + _footer()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    name = message.from_user.first_name or "друг"
    await message.answer(welcome_text(name), reply_markup=main_menu())


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Вот меню — выбирай 👇", reply_markup=main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    name = message.from_user.first_name or "друг"
    await message.answer(features_text(name), reply_markup=main_menu())


@router.message(Command("privacy", "terms"))
async def cmd_legal(message: Message) -> None:
    """Ссылки на политику конфиденциальности и условия размещения."""
    await message.answer(
        "📄 Документы:\n"
        f"• Политика конфиденциальности: {config.privacy_url()}\n"
        f"• Условия размещения: {config.terms_url()}",
        reply_markup=main_menu(),
        disable_web_page_preview=True,
    )


@router.message(F.text == BTN_STICKERS)
async def show_stickers(message: Message) -> None:
    """Кнопка «Наши стикеры» — даём ссылку на стикерпак."""
    if not config.STICKER_PACK_URL:
        return
    await message.answer(
        "Лови наши стикеры! 🎨 Жми кнопку — добавятся в один тап 👇",
        reply_markup=stickers_button(),
    )


@router.message(F.text == BTN_CANCEL)
async def cancel(message: Message, state: FSMContext) -> None:
    """Кнопка «Отмена» — выходим из любого диалога в главное меню."""
    await state.clear()
    await message.answer(
        "Без проблем, отменил! Если передумаешь — я тут 😊",
        reply_markup=main_menu(),
    )
