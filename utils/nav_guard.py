"""Кнопки меню и служебные команды всегда важнее незаконченной анкеты.

Без этого шаг анкеты (имя автора истории, вопрос в поддержку, сумма в калькуляторе)
принимал нажатие «🔍 Найти специалиста» или /start как ответ, и человек застревал.
Outer-middleware срабатывает до фильтров: сбрасывает состояние, и сообщение
доходит до своего обработчика (меню, /start с deep link и т.д.).
"""
from aiogram import BaseMiddleware
from aiogram.types import Message

from keyboards.menus import menu_texts

NAV_COMMANDS = ("/start", "/menu", "/help", "/cancel")


def is_navigation(text: str | None) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if t.startswith("/"):
        cmd = t.split()[0].split("@")[0].lower()
        return cmd in NAV_COMMANDS
    return t in menu_texts()


class NavigationGuard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and data.get("raw_state") and is_navigation(event.text):
            state = data.get("state")
            if state is not None:
                await state.clear()
            data["raw_state"] = None
        return await handler(event, data)
