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
