import json

from handlers import comment_copilot as comments


def test_style_policy_is_brand_safe_and_not_a_copy():
    prompt = comments.VOICE_RULES.lower()
    assert "собственная узнаваемая манера" in prompt
    assert "запрещено копировать" in prompt
    assert "не каждый комментарий требует ответа" in prompt
    assert "не унижай" in prompt
    assert "угрозы, травля, дискриминация" in prompt


def test_valid_reply_payload_is_normalized():
    raw = json.dumps({
        "post_context": "забастовка",
        "items": [{
            "comment": "Живут в раю и бастуют",
            "recommend_action": "reply",
            "reason": "можно разрядить",
            "replies": ["Первый", "Второй", "Третий"],
        }],
    }, ensure_ascii=False)
    payload = comments._parse_payload(raw)
    assert payload["items"][0]["replies"] == ["Первый", "Второй", "Третий"]


def test_non_reply_action_discards_generated_text():
    raw = json.dumps({
        "post_context": "пост",
        "items": [{
            "comment": "😂😂😂",
            "recommend_action": "like",
            "reason": "ответ не нужен",
            "replies": ["лишняя реплика"],
        }],
    }, ensure_ascii=False)
    payload = comments._parse_payload(raw)
    assert payload["items"][0]["replies"] == []


def test_broken_reply_payload_is_rejected():
    raw = '{"items":[{"comment":"x","recommend_action":"reply","replies":["one"]}]}'
    assert comments._parse_payload(raw) is None


def test_result_buttons_fit_telegram_callback_limit():
    payload = {
        "post_context": "пост",
        "items": [{
            "comment": "Комментарий",
            "recommend_action": "reply",
            "reason": "причина",
            "replies": ["A", "B", "C"],
        }],
    }
    keyboard = comments._result_kb("123456789abc", payload)
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert callbacks
    assert all(len(value.encode()) <= 64 for value in callbacks)


def test_accepted_examples_become_voice_context():
    class Example:
        source_comment = "Выходной сегодня"
        action = "reply"
        reply = "А так было бы два"

    prompt = comments._examples_prompt([Example()])
    assert "Выходной сегодня" in prompt
    assert "А так было бы два" in prompt
