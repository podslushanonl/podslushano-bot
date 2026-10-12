"""«Это к истории» с фото: фото доходит до модерации вместе с текстом истории."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from handlers import stories


class StoryMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_photo_carried_to_submission(self):
        state = FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=7, user_id=7))
        msg = SimpleNamespace(answer=AsyncMock())
        text = "История " * 40  # 320 символов — проходит проверку длины
        await stories.start_story_flow(msg, state, prefill=text, file_id="PHOTO1", file_type="photo")
        cb = SimpleNamespace(data="story_author:anonymous", message=msg, answer=AsyncMock(),
                             bot=object(), from_user=SimpleNamespace(id=7))
        await stories.choose_story_author(cb, state)  # текст из чата сразу уходит в предпросмотр
        self.assertEqual(await state.get_state(), stories.StoryWizard.preview.state)
        create = AsyncMock()
        with patch("handlers.submissions.create_submission", create):
            await stories.submit_story_for_moderation(cb, state)
        args = create.await_args.args
        self.assertEqual((args[2], args[4], args[5]), ("story", "PHOTO1", "photo"))
        self.assertIn("©️ Анонимно", args[3])


if __name__ == "__main__":
    unittest.main()
