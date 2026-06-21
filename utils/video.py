"""Превращение обычного видео в Telegram-кружок (video note) через ffmpeg.

Кружок должен быть квадратным и не длиннее 60 секунд. Кадрируем по центру в
квадрат, масштабируем и обрезаем по длине. ffmpeg ставится в Docker-образе.
"""
import asyncio
import logging
import shutil

log = logging.getLogger(__name__)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


async def make_circle(in_path: str, out_path: str, size: int = 480,
                      max_sec: int = 60) -> bool:
    """Кадрирует видео в квадрат и обрезает до max_sec. True при успехе."""
    if not ffmpeg_available():
        return False
    cmd = [
        "ffmpeg", "-y", "-i", in_path, "-t", str(max_sec),
        "-vf", f"crop='min(iw,ih)':'min(iw,ih)',scale={size}:{size}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart", out_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, err = await proc.communicate()
        import os
        ok = proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0
        if not ok:
            log.warning("ffmpeg circle failed: %s", (err or b"")[-300:])
        return ok
    except Exception as e:  # noqa: BLE001
        log.warning("ffmpeg error: %s", e)
        return False
