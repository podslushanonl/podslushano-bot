"""Рендер слайдов Instagram-карусели через Cloudinary URL-трансформации.

Cloudinary умеет на лету кадрировать удалённое фото (fetch) под 4:5, затемнять
его и накладывать текст — всё прямо в адресе картинки, без модулей в Make.
Нужен только Cloud name (config.CLOUDINARY_CLOUD_NAME). Бесплатного тарифа
хватает с запасом.

Возвращаем готовый URL слайда 1080×1350 — его и публикуем в Instagram.
"""
import re
from urllib.parse import quote

import config

# Размер поста Instagram 4:5
W, H = 1080, 1350


def cloudinary_enabled() -> bool:
    return bool(config.CLOUDINARY_CLOUD_NAME)


def _clean(text: str) -> str:
    """Убираем переносы строк и лишние пробелы — перенос делает сам Cloudinary."""
    return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()


def _enc_text(text: str) -> str:
    """Текст для слоя l_text. Двойное URL-кодирование: CDN раскодирует один раз,
    а запятые/слэши/кириллица должны дойти до Cloudinary всё ещё закодированными,
    иначе он примет их за служебные символы трансформации."""
    return quote(quote(_clean(text), safe=""), safe="")


def render_slide_url(photo_url: str, title: str = "", body: str = "",
                     role: str = "content") -> str | None:
    """Готовый URL слайда: фото-фон (4:5) + затемнение + текст. None — если нет
    Cloud name или фото."""
    if not (cloudinary_enabled() and photo_url):
        return None
    cloud = config.CLOUDINARY_CLOUD_NAME
    # 1) кадрируем фон под 4:5 и слегка затемняем для читаемости текста
    parts = [f"c_fill,w_{W},h_{H},g_auto", "e_brightness:-35,e_contrast:8"]
    # 2) накладываем текст
    if role == "cover":
        if title:
            parts.append(
                f"l_text:Arial_88_bold:{_enc_text(title)},"
                f"co_white,c_fit,w_920,g_center,y_0"
            )
    else:
        if title:
            parts.append(
                f"l_text:Arial_64_bold:{_enc_text(title)},"
                f"co_white,c_fit,w_940,g_north,y_140"
            )
        if body:
            parts.append(
                f"l_text:Arial_44:{_enc_text(body)},"
                f"co_white,c_fit,w_940,g_center,y_40"
            )
    transform = "/".join(parts)
    src = quote(photo_url, safe="")
    return f"https://res.cloudinary.com/{cloud}/image/fetch/{transform}/{src}"
