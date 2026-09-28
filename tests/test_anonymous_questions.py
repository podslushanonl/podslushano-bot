"""Минимальные regression-checks приватности/маршрутизации ask_alex."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from handlers.anonymous_questions import (
    _callback_question_id,
    question_target_chat_id,
    sender_hash,
)


def main() -> None:
    original_token = config.BOT_TOKEN
    original_admins = list(config.ADMIN_IDS)
    original_target = os.environ.get("ALEX_QUESTIONS_CHAT_ID")
    try:
        config.BOT_TOKEN = "test-secret-token"
        config.ADMIN_IDS[:] = [111]

        first = sender_hash(123456789)
        second = sender_hash(123456789)
        other = sender_hash(987654321)
        assert first == second
        assert first != other
        assert len(first) == 64
        assert "123456789" not in first

        os.environ.pop("ALEX_QUESTIONS_CHAT_ID", None)
        assert question_target_chat_id() == 111
        os.environ["ALEX_QUESTIONS_CHAT_ID"] = "-1001234567890"
        assert question_target_chat_id() == -1001234567890

        assert _callback_question_id("alexq:answer:42") == 42
        assert _callback_question_id("alexq:skip:not-a-number") is None
        assert _callback_question_id(None) is None
    finally:
        config.BOT_TOKEN = original_token
        config.ADMIN_IDS[:] = original_admins
        if original_target is None:
            os.environ.pop("ALEX_QUESTIONS_CHAT_ID", None)
        else:
            os.environ["ALEX_QUESTIONS_CHAT_ID"] = original_target

    print("anonymous questions checks: OK")


if __name__ == "__main__":
    main()
