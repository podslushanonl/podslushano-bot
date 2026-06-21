"""Состояния диалогов (FSM): что бот ждёт от пользователя в данный момент."""
from aiogram.fsm.state import State, StatesGroup


class StoryForm(StatesGroup):
    waiting_for_content = State()


class QuestionForm(StatesGroup):
    waiting_for_content = State()
    # ИИ ответил сам — ждём решения: спросить ли ещё и у сообщества (предложка)
    deciding = State()


class VideoForm(StatesGroup):
    waiting_for_content = State()


class AdForm(StatesGroup):
    """Пошаговая анкета рекламной заявки."""

    waiting_for_subject = State()  # что рекламируем
    waiting_for_format = State()   # формат размещения
    waiting_for_timing = State()   # желаемые сроки
    waiting_for_contact = State()  # контакт для связи


class ContactSearch(StatesGroup):
    waiting_for_query = State()


class EventsSearch(StatesGroup):
    """Раздел «Чем заняться»: ждём город для подборки событий и идей."""

    waiting_city = State()


class SupportContact(StatesGroup):
    """Обращение в поддержку: пользователь пишет, бот пересылает админам."""

    waiting_message = State()


class SupportReply(StatesGroup):
    """Ответ админа пользователю на обращение/жалобу (бот пересылает)."""

    waiting_text = State()


class LetterExplain(StatesGroup):
    """Разбор официального письма по фото."""

    waiting_photo = State()


class SalaryCalc(StatesGroup):
    """Калькулятор netto-зарплаты."""

    waiting_amount = State()


class AdminAnnounce(StatesGroup):
    """Анонс в канал с кнопкой «Открыть бота»."""

    waiting_text = State()


class AdminAfisha(StatesGroup):
    """Афиша «Чем заняться» в канал: ждём город, потом подтверждение."""

    waiting_city = State()
    confirm = State()


class AdminPost(StatesGroup):
    """Генерация поста в канал по теме: ждём тему, потом подтверждение/правки."""

    waiting_topic = State()
    confirm = State()
    editing = State()


class AdminIG(StatesGroup):
    """Instagram-карусель через Make: тема, подтверждение, правки."""

    waiting_topic = State()
    confirm = State()
    editing = State()


class AdminCircle(StatesGroup):
    """Видео-кружок в канал: ждём видео, потом подтверждение публикации."""

    waiting_video = State()
    confirm = State()


class AdminAddSpecialist(StatesGroup):
    """Пошаговое добавление специалиста админом."""

    name = State()
    category = State()
    location = State()
    description = State()
    contact = State()


class AdminFind(StatesGroup):
    """Поиск специалиста админом для удаления."""

    waiting_query = State()


class AdminBroadcast(StatesGroup):
    """Рассылка-анонс админом."""

    waiting_message = State()


class AdminSetPhoto(StatesGroup):
    """Загрузка фото для карточки специалиста (премиум)."""

    waiting_photo = State()


class ReviewForm(StatesGroup):
    """Оставить отзыв специалисту: после оценки — необязательный текст."""

    waiting_text = State()


class SelfAddSpecialist(StatesGroup):
    """Само-добавление специалиста (платно): пошаговая анкета."""

    name = State()
    category = State()
    location = State()
    description = State()
    contact = State()
    email = State()
    plan = State()
    photo = State()


class AfishaSubmit(StatesGroup):
    """Платная подача мероприятия в «Афишу месяца»: пошаговая анкета."""

    title = State()
    description = State()
    date = State()
    city = State()
    link = State()
    photo = State()
    email = State()
    month = State()


class ListingForm(StatesGroup):
    """Доска объявлений: подача объявления (бесплатно, с модерацией)."""

    title = State()
    description = State()
    price = State()
    city = State()
    photo = State()
    contact = State()


class ListingBrowse(StatesGroup):
    """Доска объявлений: ввод города при просмотре."""

    waiting_city = State()


class ClaimPay(StatesGroup):
    """Оплата «старожилом» карточки из старого гайда: спрашиваем e-mail для счёта."""

    waiting_email = State()
