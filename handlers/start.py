"""Команда /start и показ главного меню."""
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import config
from database.db import get_session
from database.models import BotUser
from keyboards.menus import (
    BTN_BACK,
    BTN_CANCEL,
    BTN_FOR_SPECIALISTS,
    BTN_MORE,
    BTN_SERVICES,
    BTN_STICKERS,
    main_menu,
    more_menu,
    services_menu,
    specialists_menu,
    stickers_button,
)

log = logging.getLogger(__name__)

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
        "✉️ Связаться с нами (вопросы и поддержка): /contact\n"
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


async def _attribute_referral(user_id: int, payload: str | None) -> None:
    """Если человек пришёл по реферальной ссылке (?start=ref_<id>) и он новичок —
    запоминаем, кто его пригласил. Атрибутируем только что зарегистрированным."""
    if not payload or not payload.startswith("ref_"):
        return
    try:
        ref_id = int(payload[4:])
    except ValueError:
        return
    if ref_id == user_id:
        return
    try:
        async with get_session() as session:
            u = await session.get(BotUser, user_id)
            if u is None or u.referred_by is not None:
                return
            # только для свежих пользователей (пришли только что по ссылке)
            if u.created_at and (datetime.utcnow() - u.created_at).total_seconds() > 600:
                return
            if await session.get(BotUser, ref_id) is None:
                return  # реферер должен существовать
            u.referred_by = ref_id
            await session.commit()
    except Exception as e:  # noqa: BLE001 — учёт не должен мешать старту
        log.warning("Не удалось учесть реферала: %s", e)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: CommandObject) -> None:
    await state.clear()
    # Пришёл по кнопке «Задать свой вопрос» из поста-предложки — сразу открываем форму
    if command.args == "ask":
        from handlers.submissions import ask_question
        await ask_question(message, state)
        return
    # Пришёл по кнопке «Разместить объявление» из поста в канале (?start=board)
    if command.args == "board":
        from handlers.board import start_new_listing
        await start_new_listing(message, state, message.from_user.id)
        return
    # Пришёл по кнопке «Подробнее» из анонса Allo Walks (?start=allo)
    if command.args == "allo":
        from handlers.allo import show_allo
        await show_allo(message, state, with_photos=True)
        return
    # Пришёл по реф-ссылке участника Allo Walks (?start=alloref_<uid>)
    if command.args and command.args.startswith("alloref_"):
        from handlers.allo import register_referral, show_allo
        try:
            ref_uid = int(command.args[len("alloref_"):])
        except ValueError:
            ref_uid = 0
        if ref_uid:
            await register_referral(ref_uid, message.from_user.id)
        await show_allo(message, state, with_photos=True)
        return
    # Пришёл по личной ссылке оплаты карточки из старого гайда (?start=claim_<id>)
    if command.args and command.args.startswith("claim_"):
        try:
            sid = int(command.args[6:])
        except ValueError:
            sid = 0
        if sid:
            from handlers.selfadd import start_claim
            await start_claim(message, sid)
            return
    # Пришёл по реф-ссылке специалиста (?start=spref_<id> — кто-то его привёл в гайд)
    if command.args and command.args.startswith("spref_"):
        try:
            ref_sid = int(command.args[6:])
        except ValueError:
            ref_sid = 0
        if ref_sid:
            from handlers.selfadd import start_specialist_referral
            await start_specialist_referral(message, ref_sid)
            return
    await _attribute_referral(message.from_user.id, command.args)
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


@router.message(F.text == BTN_SERVICES)
async def open_services(message: Message, state: FSMContext) -> None:
    """Раздел «Сервисы» — открываем подменю."""
    await state.clear()
    await message.answer("🛠 Сервисы — выбери 👇", reply_markup=services_menu())


@router.message(F.text == BTN_FOR_SPECIALISTS)
async def open_specialists(message: Message, state: FSMContext) -> None:
    """Раздел «Специалистам и рекламодателям» — открываем подменю."""
    await state.clear()
    await message.answer(
        "💼 Для специалистов и рекламодателей — выбери 👇",
        reply_markup=specialists_menu(),
    )


@router.message(F.text == BTN_MORE)
async def open_more(message: Message, state: FSMContext) -> None:
    """Раздел «Ещё» — связаться и поделиться."""
    await state.clear()
    await message.answer("☰ Ещё — выбери 👇", reply_markup=more_menu())


@router.message(F.text == BTN_BACK)
async def back_to_main(message: Message, state: FSMContext) -> None:
    """Возврат из подменю в главное меню."""
    await state.clear()
    await message.answer("Главное меню 👇", reply_markup=main_menu())


@router.message(F.text == BTN_CANCEL)
async def cancel(message: Message, state: FSMContext) -> None:
    """Кнопка «Отмена» — выходим из любого диалога в главное меню."""
    await state.clear()
    await message.answer(
        "Без проблем, отменил! Если передумаешь — я тут 😊",
        reply_markup=main_menu(),
    )
