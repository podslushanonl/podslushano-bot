"""Кнопки меню и /start, /menu, /help, /cancel прерывают незаконченную анкету."""
import unittest
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Chat, Message, Update, User

from keyboards.menus import BTN_CONTACTS, BTN_HOME, OLD_BTN_HOME
from utils.nav_guard import NavigationGuard, is_navigation


class Form(StatesGroup):
    name = State()


def upd(text: str, n: int) -> Update:
    msg = Message(message_id=n, date=datetime.now(), chat=Chat(id=7, type="private"),
                  from_user=User(id=7, is_bot=False, first_name="T"), text=text)
    return Update(update_id=n, message=msg)


class NavGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen = []
        early, late = Router(), Router()

        @early.message(Form.name)  # анкета зарегистрирована раньше меню, как StoryWizard
        async def take_name(message: Message, state: FSMContext):
            self.seen.append(("form", message.text))

        @late.message(CommandStart())
        async def start(message: Message):
            self.seen.append(("start", message.text))

        @late.message(F.text == BTN_CONTACTS)
        async def contacts(message: Message):
            self.seen.append(("contacts", message.text))

        @late.message(Command("go"))
        async def go(message: Message, state: FSMContext):
            await state.set_state(Form.name)

        self.dp = Dispatcher()
        self.dp.message.outer_middleware(NavigationGuard())
        self.dp.include_router(early)
        self.dp.include_router(late)
        self.bot = Bot("123456:TEST")
        self.n = 0

    async def asyncTearDown(self):
        await self.bot.session.close()

    async def send(self, text):
        self.n += 1
        await self.dp.feed_update(self.bot, upd(text, self.n))

    async def test_menu_button_and_start_escape_the_form(self):
        await self.send("/go")
        await self.send("Анна")
        self.assertEqual(self.seen[-1], ("form", "Анна"))
        await self.send(BTN_CONTACTS)
        self.assertEqual(self.seen[-1], ("contacts", BTN_CONTACTS))
        await self.send("/go")
        await self.send("/start ask")
        self.assertEqual(self.seen[-1], ("start", "/start ask"))
        await self.send("обычный текст")  # анкета уже сброшена — форма больше не ловит
        self.assertEqual(len([s for s in self.seen if s[0] == "form"]), 1)

    def test_is_navigation(self):
        for t in ("/start", "/menu@podslushano_nl_bot", "/cancel", BTN_HOME, OLD_BTN_HOME, "🍂 Афиша"):
            self.assertTrue(is_navigation(t), t)
        for t in ("Анна", "/afisha_add", "Где посмотреть Афиша", ""):
            self.assertFalse(is_navigation(t), t)


if __name__ == "__main__":
    unittest.main()
