"""Рендер слайдов Instagram-карусели прямо в боте (Pillow), бесплатно.

Стиль под бренд: фото на весь кадр (4:5, 1080×1350), мягкое затемнение снизу,
тонкий оранжевый акцент, узкий жирный КАПС-заголовок (Oswald) и описание
(Montserrat), водяной знак @podslushano.nl по центру. Cloudinary не нужен.

Готовые JPEG-байты складываем в память и отдаём по ссылке через веб-сервер
(см. utils/webserver: /ig-slide/<id>.jpg) — оттуда их забирает Make/Instagram.
"""
from __future__ import annotations

import io
import logging
import os
import uuid
from collections import OrderedDict

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

import config

log = logging.getLogger(__name__)

W, H = 1080, 1350
ORANGE = (243, 124, 32)
WHITE = (255, 255, 255)
MARGIN = 80
WATERMARK = "@podslushano.nl"

_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts")
_OSWALD = os.path.join(_FONT_DIR, "Oswald.ttf")
_MONT = os.path.join(_FONT_DIR, "Montserrat.ttf")
_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Фирменные шрифты и маскот для финального CTA-слайда
_MONT_HEAVY = os.path.join(_FONT_DIR, "Mont-Heavy.otf")
_EVOLVENTA = os.path.join(_FONT_DIR, "Evolventa-Regular.otf")
_EVOLVENTA_B = os.path.join(_FONT_DIR, "Evolventa-Bold.otf")
_DEER = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "mascot", "deer.png")
CTA_ORANGE = (232, 112, 28)
SOFT = (255, 238, 222)
# Фиксированный текст CTA (всегда одинаковый)
CTA_HEADLINE = ["НИДЕРЛАНДЫ", "КАК ОНИ ЕСТЬ"]
CTA_SUB = ["Показываем страну изнутри,", "без глянца и прикрас."]
CTA_IG = "Instagram  @podslushano.nl"
CTA_TG = "Telegram  @podslushanovnl"

# Простейшее хранилище готовых картинок: id -> jpeg-байты (живут до перезапуска)
_STORE: "OrderedDict[str, bytes]" = OrderedDict()
_STORE_MAX = 120


def slides_enabled() -> bool:
    """Рендер возможен, если есть шрифты и задан публичный адрес для отдачи."""
    return os.path.exists(_OSWALD) and bool(config.WEBHOOK_BASE_URL)


def _font(path: str, size: int, weight: int):
    try:
        f = ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001 — нет шрифта → дежурный DejaVu
        f = ImageFont.truetype(_FALLBACK, size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:  # noqa: BLE001 — статический шрифт, без осей
        pass
    return f


def _osw(size: int, weight: int = 700):
    return _font(_OSWALD, size, weight)


def _mont(size: int, weight: int = 600):
    return _font(_MONT, size, weight)


def _energy_offset(im: Image.Image, win: int, vertical: bool) -> int:
    """Где главное «содержание» кадра: окно длиной win с максимумом краёв/деталей.
    vertical=False — двигаем окно по X (широкое фото), True — по Y (высокое)."""
    try:
        edges = im.convert("L").filter(ImageFilter.FIND_EDGES)
        if vertical:
            edges = edges.transpose(Image.ROTATE_90)  # строки → столбцы
        full = edges.width
        sw = 240
        ratio = sw / full
        small = edges.resize((sw, 1))  # сжимаем по высоте до 1 строки = сумма энергии столбцов
        cols = list(small.getdata())
        wwin = max(1, int(win * ratio))
        if wwin >= len(cols):
            return 0
        pref = [0]
        for c in cols:
            pref.append(pref[-1] + c)
        best_i, best = 0, -1
        for i in range(0, len(cols) - wwin + 1):
            s = pref[i + wwin] - pref[i]
            if s > best:
                best, best_i = s, i
        return int(best_i / ratio)
    except Exception:  # noqa: BLE001 — при сбое берём центр
        return -1


def _cover_crop(src: Image.Image) -> Image.Image:
    """Кадрирует под 1080×1350, оставляя самую «насыщенную» часть кадра
    (а не слепой центр), чтобы не отрезать главный объект."""
    im = src.convert("RGB")
    r = max(W / im.width, H / im.height)
    im = im.resize((max(W, int(im.width * r)), max(H, int(im.height * r))))
    if im.width > W:  # широкое → выбираем окно по горизонтали
        off = _energy_offset(im, W, vertical=False)
        x = (im.width - W) // 2 if off < 0 else min(max(0, off), im.width - W)
        y = 0
    else:  # высокое → выбираем окно по вертикали
        off = _energy_offset(im, H, vertical=True)
        x = 0
        y = (im.height - H) // 2 if off < 0 else min(max(0, off), im.height - H)
    return im.crop((x, y, x + W, y + H))


def _scrim(img: Image.Image, bot_alpha: int, bot_frac: float) -> Image.Image:
    """Плавное затемнение снизу — чтобы текст читался на любом фото."""
    g = Image.new("L", (1, H), 0)
    bstart = int(H * (1 - bot_frac))
    for y in range(H):
        a = int(bot_alpha * ((y - bstart) / (H - bstart)) ** 1.25) if y >= bstart else 0
        g.putpixel((0, y), a)
    g = g.resize((W, H))
    return Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, g)


def _wrap(d: ImageDraw.ImageDraw, text: str, f, max_w: int) -> list[str]:
    out: list[str] = []
    cur = ""
    for w in text.split():
        s = (cur + " " + w).strip()
        if d.textlength(s, font=f) <= max_w:
            cur = s
        else:
            if cur:
                out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


def _fit_title(d, text: str, max_w: int, max_lines: int, hi: int, lo: int):
    """Подбирает крупнейший размер Oswald, при котором заголовок влезает."""
    for s in range(hi, lo, -3):
        f = _osw(s, 700)
        lines = _wrap(d, text, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
    f = _osw(lo, 700)
    return f, _wrap(d, text, f, max_w)


def _soft(img: Image.Image, draw_fn) -> Image.Image:
    """Рисует с мягкой тенью: текст по чёрному + размытие, затем сам текст."""
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(sh), (0, 0, 0, 180))
    sh = sh.filter(ImageFilter.GaussianBlur(6))
    base = img.convert("RGBA")
    base.alpha_composite(sh)
    draw_fn(ImageDraw.Draw(base), None)
    return base.convert("RGB")


def _watermark(img: Image.Image) -> None:
    ImageDraw.Draw(img).text(
        (W // 2, H - 56), WATERMARK, font=_mont(26, 600),
        fill=(235, 235, 235), anchor="ma",
    )


def render_cover(photo: Image.Image, title: str) -> Image.Image:
    img = _scrim(_cover_crop(photo), 238, 0.5)
    d = ImageDraw.Draw(img)
    f, lines = _fit_title(d, (title or "").upper(), W - 2 * MARGIN - 10, 4, 120, 70)
    lh = f.size * 1.0
    ytop = H - 130 - len(lines) * lh

    def draw(dd, col):
        if col is None:
            dd.rectangle([MARGIN, ytop - 34, MARGIN + 90, ytop - 26], fill=ORANGE)
        y = ytop
        for ln in lines:
            dd.text((MARGIN, y), ln, font=f, fill=(WHITE if col is None else col))
            y += lh

    img = _soft(img, draw)
    _watermark(img)
    return img


def render_content(photo: Image.Image, title: str, body: str) -> Image.Image:
    img = _scrim(_cover_crop(photo), 242, 0.58)
    d = ImageDraw.Draw(img)
    tf = _osw(64, 700)
    tlines = _wrap(d, (title or "").upper(), tf, W - 2 * MARGIN)
    bf = _mont(42, 500)
    blines = _wrap(d, body or "", bf, W - 2 * MARGIN)
    th = len(tlines) * tf.size
    bh = len(blines) * bf.size * 1.32
    ytop = H - 120 - th - 26 - bh

    def draw(dd, col):
        if col is None:
            dd.rectangle([MARGIN, ytop - 30, MARGIN + 90, ytop - 23], fill=ORANGE)
        y = ytop
        for ln in tlines:
            dd.text((MARGIN, y), ln, font=tf, fill=(ORANGE if col is None else col))
            y += tf.size
        y += 26
        for ln in blines:
            dd.text((MARGIN, y), ln, font=bf, fill=(WHITE if col is None else col))
            y += bf.size * 1.32

    img = _soft(img, draw)
    _watermark(img)
    return img


async def _fetch_image(url: str) -> Image.Image | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status >= 300:
                    return None
                data = await r.read()
        return Image.open(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        log.warning("slides: не скачал фото %s: %s", url, e)
        return None


def _store(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    sid = uuid.uuid4().hex
    _STORE[sid] = buf.getvalue()
    while len(_STORE) > _STORE_MAX:
        _STORE.popitem(last=False)
    return sid


def get_slide(sid: str) -> bytes | None:
    return _STORE.get(sid)


def _public_url(sid: str) -> str:
    return f"{config.WEBHOOK_BASE_URL or ''}/ig-slide/{sid}.jpg"


async def make_slide_url(photo_url: str, title: str, body: str, role: str) -> str | None:
    """Скачивает фото, рисует слайд, кладёт в память и возвращает публичный URL.
    None — если рендер невозможен или фото не скачалось."""
    if not slides_enabled() or not photo_url:
        return None
    photo = await _fetch_image(photo_url)
    if photo is None:
        return None
    try:
        if role == "cover":
            img = render_cover(photo, title)
        else:
            img = render_content(photo, title, body)
    except Exception as e:  # noqa: BLE001
        log.warning("slides: ошибка рендера: %s", e)
        return None
    return _public_url(_store(img))


def _ttf(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001
        return ImageFont.truetype(_FALLBACK, size)


def render_cta(photo: Image.Image | None) -> Image.Image:
    """Фиксированный фирменный CTA-слайд: фото сверху + оранжевый снизу,
    жирный заголовок (Mont Heavy), текст (Evolventa), маскот-лосёнок справа."""
    base = _cover_crop(photo) if photo is not None else Image.new("RGB", (W, H), (150, 168, 150))
    base = ImageEnhance.Brightness(base).enhance(0.97)
    img = base.convert("RGBA")

    # КОСОЙ срез фото→оранжевый (как в эталоне): слева ниже, справа выше.
    cut_l, cut_r = int(H * 0.60), int(H * 0.53)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon([(0, cut_l), (W, cut_r), (W, H), (0, H)], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(1))
    orange = Image.new("RGBA", (W, H), CTA_ORANGE + (255,))
    orange.putalpha(mask)
    img.alpha_composite(orange)

    # маскот справа, вровень с текстом, целиком внутри оранжевой плашки.
    # Кропнутый PNG дополняем прозрачными полями, чтобы кремовая обводка и рога
    # не обрезались по краям.
    try:
        deer = Image.open(_DEER).convert("RGBA")
        dh = 460
        dw = int(deer.width * dh / deer.height)
        deer = deer.resize((dw, dh))
        pad = 26
        canvas = Image.new("RGBA", (dw + 2 * pad, dh + 2 * pad), (0, 0, 0, 0))
        canvas.alpha_composite(deer, (pad, pad))
        deer = canvas
        dw, dh = deer.size
        dx, dy = W - dw - 40, cut_r + 6
        grown = deer.getchannel("A").filter(ImageFilter.MaxFilter(15))
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).ellipse([dx + 40, dy + dh - 40, dx + dw - 40, dy + dh + 16], fill=(0, 0, 0, 55))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(15)))
        outline = Image.new("RGBA", (dw, dh), (250, 242, 228, 255))
        outline.putalpha(grown)
        img.alpha_composite(outline, (dx, dy))
        img.alpha_composite(deer, (dx, dy))
    except Exception as e:  # noqa: BLE001 — без маскота тоже соберём
        log.warning("slides: маскот не вставился: %s", e)

    def shadow_text(xy, txt, f, fill):
        x, y = xy
        s = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(s).text((x, y), txt, font=f, fill=(0, 0, 0, 90))
        img.alpha_composite(s.filter(ImageFilter.GaussianBlur(4)))
        ImageDraw.Draw(img).text((x, y), txt, font=f, fill=fill)

    x = 80
    y = 838
    hf = _ttf(_MONT_HEAVY, 70)
    for ln in CTA_HEADLINE:
        shadow_text((x, y), ln, hf, WHITE)
        y += 80
    y = 1014
    sf = _ttf(_EVOLVENTA, 32)
    for ln in CTA_SUB:
        shadow_text((x, y), ln, sf, SOFT)
        y += 44
    # контакты: подпись (кремовая) + ник (белый жирный)
    y = 1150
    lf = _ttf(_EVOLVENTA, 29)
    vf = _ttf(_EVOLVENTA_B, 29)
    for label, value in (("Instagram", "@podslushano.nl"), ("Telegram", "@podslushanovnl")):
        shadow_text((x, y), label, lf, SOFT)
        lw = ImageDraw.Draw(img).textlength(label, font=lf)
        shadow_text((x + lw + 18, y), value, vf, WHITE)
        y += 48
    return img.convert("RGB")


async def make_cta_url(photo_url: str | None) -> str | None:
    """Рисует фиксированный CTA на фоне переданного фото (или без него),
    кладёт в память и возвращает публичный URL."""
    if not slides_enabled():
        return None
    photo = await _fetch_image(photo_url) if photo_url else None
    try:
        img = render_cta(photo)
    except Exception as e:  # noqa: BLE001
        log.warning("slides: ошибка рендера CTA: %s", e)
        return None
    return _public_url(_store(img))
