"""Отправка стикеров из вашего собственного стикерпака.

Бот один раз подгружает стикерпак по короткому имени (config.STICKER_SET_NAME)
и дальше шлёт подходящий стикер под событие: приветствие, благодарность за
заявку, успешный поиск. Стикер подбирается по эмодзи, а если не нашёлся —
по запасному правилу. Если пак не задан или недоступен — бот просто молчит
стикерами, всё остальное работает.
"""
from __future__ import annotations

import logging

from aiogram import Bot

import config

log = logging.getLogger(__name__)

# Кэш загруженного пака: список (file_id, emoji)
_stickers: list[tuple[str, str]] | None = None
_load_failed = False

# Какие эмодзи предпочесть под каждое событие (по убыванию приоритета)
PURPOSE_EMOJI = {
    "welcome": ["👋", "🤗", "😊", "🙂", "🇳🇱", "❤️", "🙌"],
    "thanks": ["🙏", "❤️", "🤗", "😘", "💚", "✨", "🥰"],
    "found": ["🎉", "🥳", "👍", "😎", "🔥", "✨", "💪"],
}
# Запасной индекс стикера, если по эмодзи не нашли (стабильный для события)
PURPOSE_FALLBACK_INDEX = {"welcome": 0, "thanks": 1, "found": 2}


async def _ensure_loaded(bot: Bot) -> None:
    """Лениво загружает стикерпак (один раз за время работы бота)."""
    global _stickers, _load_failed
    if _stickers is not None or _load_failed:
        return
    if not config.STICKER_SET_NAME:
        _load_failed = True
        return
    try:
        sticker_set = await bot.get_sticker_set(config.STICKER_SET_NAME)
        _stickers = [(s.file_id, s.emoji or "") for s in sticker_set.stickers]
        if not _stickers:
            _load_failed = True
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось загрузить стикерпак %s: %s", config.STICKER_SET_NAME, e)
        _load_failed = True


def _pick(purpose: str) -> str | None:
    """Выбирает file_id стикера под событие из загруженного пака."""
    if not _stickers:
        return None
    for emoji in PURPOSE_EMOJI.get(purpose, []):
        for file_id, sticker_emoji in _stickers:
            if emoji and emoji in sticker_emoji:
                return file_id
    # По эмодзи не нашли — берём по стабильному индексу
    index = PURPOSE_FALLBACK_INDEX.get(purpose, 0)
    if index < len(_stickers):
        return _stickers[index][0]
    return _stickers[0][0]


async def send_sticker(bot: Bot, chat_id: int, purpose: str) -> None:
    """Отправляет стикер под событие. Молча ничего не делает, если пак не задан."""
    await _ensure_loaded(bot)
    file_id = _pick(purpose)
    if not file_id:
        return
    try:
        await bot.send_sticker(chat_id, file_id)
    except Exception as e:  # noqa: BLE001 — стикер не критичен
        log.warning("Не удалось отправить стикер (%s): %s", purpose, e)
