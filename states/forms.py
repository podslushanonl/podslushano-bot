"""Состояния диалогов (FSM): что бот ждёт от пользователя в данный момент."""
from aiogram.fsm.state import State, StatesGroup


class StoryForm(StatesGroup):
    waiting_for_content = State()


class QuestionForm(StatesGroup):
    waiting_for_content = State()


class VideoForm(StatesGroup):
    waiting_for_content = State()


class AdForm(StatesGroup):
    waiting_for_content = State()


class ContactSearch(StatesGroup):
    waiting_for_query = State()
