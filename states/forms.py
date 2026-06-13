"""Состояния диалогов (FSM): что бот ждёт от пользователя в данный момент."""
from aiogram.fsm.state import State, StatesGroup


class StoryForm(StatesGroup):
    waiting_for_content = State()


class QuestionForm(StatesGroup):
    waiting_for_content = State()


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
