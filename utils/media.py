"""Файлы сторис и видео Pulse на диске сервера (на Railway — постоянный том /app/data).

Загрузка — multipart/form-data потоком прямо в файл (видео не держим в памяти целиком). Фото пересохраняется
в JPEG (без метаданных и геопозиции), видео проверяется по сигнатуре (MP4/MOV/WebM) и размеру.
Имя файла — случайное, его не угадать; отдаётся GET /media/{папка}/{файл} с поддержкой перемотки (Range).
"""
from __future__ import annotations

import io
import logging
import os
import re
import secrets
from pathlib import Path

from aiohttp import web

import config

log = logging.getLogger(__name__)

MEDIA_DIR = Path(os.getenv("MEDIA_DIR") or Path(config.DB_PATH).parent / "media")
FOLDERS = ("stories", "pulse")
VIDEO_MAX = 80 * 1024 * 1024
PHOTO_MAX = 15 * 1024 * 1024
PHOTO_SIDE = 1920
_NAME = re.compile(r"^[a-f0-9]{32}\.(jpg|mp4|mov|webm)$")


class UploadError(Exception):
    """Понятная человеку причина, почему файл не принят."""


def _kind(head: bytes) -> str | None:
    """Тип файла по первым байтам: jpg | png | heic | mp4 | mov | webm."""
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"mif1", b"msf1"):
            return "heic"
        return "mov" if brand == b"qt  " else "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return None


def path(folder: str, name: str) -> Path:
    return MEDIA_DIR / folder / name


def url(folder: str, name: str) -> str:
    return f"/media/{folder}/{name}"


def remove(folder: str, name: str) -> None:
    try:
        path(folder, name).unlink(missing_ok=True)
    except OSError as e:
        log.warning("Медиа: не удалён %s/%s: %s", folder, name, e)


async def read_upload(request: web.Request, folder: str, allow: tuple[str, ...]) -> tuple[dict, str, str]:
    """Читает multipart: текстовые поля и один файл (поле file). Возвращает (поля, тип photo|video, имя файла).
    allow — какие типы принимаются: ("photo",), ("video",) или оба."""
    if not request.content_type.startswith("multipart/"):
        raise UploadError("Файл не получен. Попробуйте ещё раз.")
    fields: dict = {}
    saved: tuple[str, str] | None = None
    reader = await request.multipart()
    async for part in reader:
        if part.name != "file":
            fields[part.name] = (await part.text())[:2000]
            continue
        if saved:
            continue
        saved = await _save_part(part, folder, allow)
    if not saved:
        raise UploadError("Добавьте фото или видео.")
    return fields, saved[0], saved[1]


async def _save_part(part, folder: str, allow: tuple[str, ...]) -> tuple[str, str]:
    head = await part.read_chunk(64 * 1024)
    kind = _kind(head[:16])
    if kind == "heic":   # HEIC сервер не читает: приложение само присылает JPEG, это — файл «как есть»
        raise UploadError("Фото в формате HEIC не подходит — выберите JPEG или сделайте снимок заново.")
    media = "photo" if kind in ("jpg", "png") else "video" if kind in ("mp4", "mov", "webm") else None
    if not media or media not in allow:
        raise UploadError("Этот формат не подходит. Нужны фото JPEG/PNG или видео MP4/MOV." if "video" in allow
                          else "Нужно фото JPEG или PNG.")
    (MEDIA_DIR / folder).mkdir(parents=True, exist_ok=True)
    if media == "photo":
        if len(head) > PHOTO_MAX:
            raise UploadError("Фото слишком большое: до 15 МБ.")
        data = bytearray(head)
        while chunk := await part.read_chunk(256 * 1024):
            data += chunk
            if len(data) > PHOTO_MAX:
                raise UploadError("Фото слишком большое: до 15 МБ.")
        name = f"{secrets.token_hex(16)}.jpg"
        path(folder, name).write_bytes(_jpeg(bytes(data)))
        return "photo", name
    if len(head) > VIDEO_MAX:
        raise UploadError("Видео слишком большое: до 80 МБ.")
    name = f"{secrets.token_hex(16)}.{kind}"
    target, size = path(folder, name), len(head)
    try:
        with open(target, "wb") as f:
            f.write(head)
            while chunk := await part.read_chunk(256 * 1024):
                size += len(chunk)
                if size > VIDEO_MAX:
                    raise UploadError("Видео слишком большое: до 80 МБ.")
                f.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return "video", name


def _jpeg(raw: bytes) -> bytes:
    """Фото → JPEG до 1920 px по большей стороне, с учётом поворота и без метаданных (геопозиции)."""
    from PIL import Image, ImageOps
    try:
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
    except Exception as e:  # noqa: BLE001
        raise UploadError("Не получилось прочитать фото. Попробуйте другое.") from e
    im = im.convert("RGB")
    im.thumbnail((PHOTO_SIDE, PHOTO_SIDE))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


async def serve(request: web.Request) -> web.StreamResponse:
    folder, name = request.match_info["folder"], request.match_info["name"]
    p = path(folder, name)
    if folder not in FOLDERS or not _NAME.match(name) or not p.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(p, headers={"Cache-Control": "public, max-age=604800, immutable"})


def install_routes(app: web.Application) -> None:
    app.router.add_get(r"/media/{folder}/{name}", serve)
