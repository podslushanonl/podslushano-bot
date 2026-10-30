"""Фото премиум-карточки из анкеты на сайте.

Анкета на сайте присылает фото вместе с заявкой, до оплаты. Файл сохраняется на диск
(JPEG до 1200 px), а после оплаты бот отправляет его админам вместе с заявкой на
проверку: так у карточки появляется photo_file_id Telegram, как у фото, присланных
в боте, и дальше фото показывается везде одинаково — в боте, на сайте и в канале.
"""
from __future__ import annotations

import logging
import os
from io import BytesIO

import config

log = logging.getLogger(__name__)

PHOTO_DIR = os.path.join(os.path.dirname(config.DB_PATH), "specialist_photos")
MAX_BYTES = 8 * 1024 * 1024


def path(sid: int) -> str:
    return os.path.join(PHOTO_DIR, f"{int(sid)}.jpg")


def exists(sid: int) -> bool:
    return os.path.exists(path(sid))


def to_jpeg(blob: bytes) -> bytes | None:
    """Приводит картинку к JPEG до 1200 px; None, если это не изображение."""
    try:
        from PIL import Image, ImageOps

        im = Image.open(BytesIO(blob))
        im.load()
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            rgba = im.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.split()[-1])
            im = bg
        im = im.convert("RGB")
        im.thumbnail((1200, 1200))
        out = BytesIO()
        im.save(out, "JPEG", quality=86, optimize=True)
        return out.getvalue()
    except Exception as e:  # noqa: BLE001
        log.info("Фото карточки не открылось: %s", e)
        return None


def save(sid: int, blob: bytes) -> bool:
    jpeg = to_jpeg(blob) if blob and len(blob) <= MAX_BYTES else None
    if not jpeg:
        return False
    os.makedirs(PHOTO_DIR, exist_ok=True)
    with open(path(sid), "wb") as fh:
        fh.write(jpeg)
    return True


def read(sid: int) -> bytes | None:
    try:
        with open(path(sid), "rb") as fh:
            return fh.read()
    except OSError:
        return None


async def attach_to_telegram(bot, sid: int, caption: str) -> str | None:
    """Отправляет фото с диска первому админу и сохраняет его photo_file_id в карточке."""
    from aiogram.types import BufferedInputFile

    from database.db import get_session
    from database.models import Specialist

    async with get_session() as session:
        sp = await session.get(Specialist, sid)
        if sp is None or sp.photo_file_id:
            return sp.photo_file_id if sp else None
    blob = read(sid)
    if not blob or not config.ADMIN_IDS:
        return None
    try:
        msg = await bot.send_photo(config.ADMIN_IDS[0], BufferedInputFile(blob, filename=f"{sid}.jpg"),
                                   caption=caption)
    except Exception as e:  # noqa: BLE001
        log.warning("Фото карточки #%s не отправлено в Telegram: %s", sid, e)
        return None
    file_id = msg.photo[-1].file_id if msg.photo else None
    if file_id:
        async with get_session() as session:
            sp = await session.get(Specialist, sid)
            if sp is not None and not sp.photo_file_id:
                sp.photo_file_id = file_id
                await session.commit()
    return file_id
