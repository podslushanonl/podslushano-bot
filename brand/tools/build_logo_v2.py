"""Второй круг логотипа podslushano.nl: мягкие живые формы, без углов.

Надпись — Nunito Black (скруглённые концы букв, лицензия OFL), переведена в кривые.
Знаки построены кривыми Безье по сетке 100x100.

Запуск из корня репозитория:  python3 brand/tools/build_logo_v2.py
Результат: brand/logo/concepts-v2/<вариант>/*.svg
"""
from __future__ import annotations

from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "logo" / "concepts-v2"
FONT = ROOT / "fonts" / "Nunito_900Black.ttf"

ACCENT = "#FF5A1F"
INK = "#0D1117"
PAPER = "#FFFFFF"
NIGHT = "#0E1014"

# тёплая гамма вокруг фирменного оранжевого — для знаков и иконки
SUN = "#FFB23F"      # тёплый жёлтый
TANGERINE = "#FF8A2B"
CORAL = "#FF4F5E"    # коралловый
LEAF = "#2FA36B"     # зелёный стебля


def text_paths(text: str, size: float, x0: float, baseline: float, tracking: float = -0.01):
    font = TTFont(FONT)
    upm = font["head"].unitsPerEm
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    k = size / upm
    pen = SVGPathPen(gs)
    x = x0
    for ch in text:
        name = cmap[ord(ch)]
        gs[name].draw(TransformPen(pen, (k, 0, 0, -k, x, baseline)))
        x += hmtx[name][0] * k + tracking * size
    return pen.getCommands(), x - x0 - tracking * size


def defs(uid: str) -> str:
    return (
        "<defs>"
        f'<linearGradient id="g{uid}" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{SUN}"/><stop offset=".5" stop-color="{ACCENT}"/><stop offset="1" stop-color="{CORAL}"/>'
        "</linearGradient>"
        f'<linearGradient id="t{uid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{TANGERINE}"/><stop offset="1" stop-color="{CORAL}"/>'
        "</linearGradient>"
        "</defs>"
    )


# ----------------------------------------------------------------- знаки

def mark_melnitsa(uid: str, mono: str | None = None) -> str:
    """«Мельница»: четыре мягких лопасти-лепестка вертушкой. Мельница, цветок и движение сразу."""
    blade = "M50 50C47 38 44 22 52 13C59 5 72 9 72 21C72 33 61 42 50 50Z"
    cols = [SUN, ACCENT, CORAL, TANGERINE] if not mono else [mono] * 4
    parts = [f'<path d="{blade}" fill="{c}" transform="rotate({a} 50 50)"/>' for a, c in zip((0, 90, 180, 270), cols)]
    hub = PAPER if not mono else "none"
    parts.append(f'<circle cx="50" cy="50" r="5.5" fill="{hub}"/>')
    return "".join(parts)


def mark_tyulpan(uid: str, mono: str | None = None) -> str:
    """«Тюльпан»: средний лепесток — облачко речи, боковые обнимают его. Голландия и разговор."""
    fill_side = mono or f"url(#t{uid})"
    fill_mid = mono or f"url(#g{uid})"
    stem = mono or LEAF
    return (
        f'<path d="M50 88C50 80 50 74 50 66" stroke="{stem}" stroke-width="6" stroke-linecap="round" fill="none"/>'
        f'<path d="M50 80C58 70 70 68 78 72C72 82 60 84 50 80Z" fill="{stem}"/>'
        f'<path d="M48 68C30 68 18 54 20 32C32 34 44 44 48 68Z" fill="{fill_side}"/>'
        f'<path d="M52 68C70 68 82 54 80 32C68 34 56 44 52 68Z" fill="{fill_side}"/>'
        f'<path d="M50 12C62 20 68 34 66 48C64 60 56 67 50 68C44 67 36 60 34 48C32 34 38 20 50 12Z" fill="{fill_mid}"/>'
    )


def mark_vertushka(uid: str, mono: str | None = None) -> str:
    """«Вертушка»: четыре облачка речи кружатся вокруг центра. Разговоры со всех сторон и голландская мельница."""
    bubble = "M50 50C50 45 51 41 53 38C49 35 47 31 47 27C47 19 54 13 62 13C70 13 76 19 76 27C76 35 70 41 62 41C60 41 58 41 56 40C54 44 52 47 50 50Z"
    cols = [SUN, ACCENT, CORAL, TANGERINE] if not mono else [mono] * 4
    return "".join(f'<path d="{bubble}" fill="{c}" transform="rotate({a} 50 50)"/>' for a, c in zip((0, 90, 180, 270), cols))


MARKS = {
    "d-melnitsa": ("Мельница", mark_melnitsa, (5, 5, 95, 95)),
    "e-tyulpan": ("Тюльпан", mark_tyulpan, (18, 10, 82, 91)),
    "f-vertushka": ("Вертушка", mark_vertushka, (13, 13, 87, 87)),
}


def fit(body: str, bbox, x: float, y: float, h: float):
    x0, y0, x1, y1 = bbox
    k = h / (y1 - y0)
    return f'<g transform="translate({x - x0 * k:.2f} {y - y0 * k:.2f}) scale({k:.4f})">{body}</g>', (x1 - x0) * k


def svg(w: float, h: float, body: str, title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" height="{h:.0f}" role="img">'
            f"<title>{title}</title>{body}</svg>\n")


def wordmark(fg: str, x: float, baseline: float, size: float):
    d1, w1 = text_paths("podslushano", size, x, baseline)
    d2, w2 = text_paths(".nl", size, x + w1, baseline)
    return f'<path d="{d1}" fill="{fg}"/><path d="{d2}" fill="{ACCENT}"/>', w1 + w2


def build() -> None:
    size, mark_h, gap, pad = 64, 88, 18, 8
    for key, (label, fn, bbox) in MARKS.items():
        d = OUT / key
        d.mkdir(parents=True, exist_ok=True)
        for theme, fg in (("light", INK), ("dark", PAPER)):
            uid = f"{key[0]}{theme[0]}"
            m, mw = fit(fn(uid), bbox, 0, 0, 100)
            (d / f"mark-{theme}.svg").write_text(svg(mw, 100, defs(uid) + m, f"podslushano.nl, знак «{label}»"))
            words, ww = wordmark(fg, 0, 0, size)
            m, mw = fit(fn(uid), bbox, pad, pad, mark_h)
            base = pad + mark_h / 2 + size * 0.25
            body = defs(uid) + m + f'<g transform="translate({pad + mw + gap:.2f} {base:.2f})">{words}</g>'
            (d / f"logo-horizontal-{theme}.svg").write_text(svg(pad + mw + gap + ww + pad, mark_h + 2 * pad, body, "podslushano.nl"))
        # одноцветный знак (печать, вышивка, водяной знак)
        m, mw = fit(fn("m", mono=INK), bbox, 0, 0, 100)
        (d / "mark-mono.svg").write_text(svg(mw, 100, m, f"podslushano.nl, знак «{label}», один цвет"))
        # иконки приложения: светлая плитка с цветным знаком и тёмная плитка
        x0, y0, x1, y1 = bbox
        for name, bg in (("app-icon", "#FFF6EF"), ("app-icon-dark", NIGHT)):
            uid = f"{key[0]}{name[-1]}"
            h = 640
            w = (x1 - x0) * h / (y1 - y0)
            if w > 680:
                h, w = h * 680 / w, 680
            m, _ = fit(fn(uid), bbox, (1024 - w) / 2, (1024 - h) / 2, h)
            (d / f"{name}.svg").write_text(svg(1024, 1024, defs(uid) + f'<rect width="1024" height="1024" fill="{bg}"/>' + m, "podslushano.nl"))
    for theme, fg in (("light", INK), ("dark", PAPER)):
        words, ww = wordmark(fg, pad, pad + size * 0.76, size)
        (OUT / f"wordmark-{theme}.svg").write_text(svg(ww + 2 * pad, size + 2 * pad, words, "podslushano.nl"))
    print("готово:", OUT)


if __name__ == "__main__":
    build()
