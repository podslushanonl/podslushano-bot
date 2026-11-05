"""Сборка логотипов podslushano.nl в SVG.

Надпись переводится в кривые из шрифта (Montserrat ExtraBold, лицензия OFL),
поэтому SVG не зависит от установленных шрифтов. Знаки построены по сетке 100x100.

Запуск из корня репозитория:  python3 brand/tools/build_logo.py
Результат: brand/logo/concepts/<вариант>/*.svg
"""
from __future__ import annotations

import math
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "logo" / "concepts"
FONT = ROOT / "fonts" / "Montserrat_800ExtraBold.ttf"

ACCENT = "#FF5A1F"   # фирменный оранжевый (как на сайте)
INK = "#0D1117"      # основной тёмный
PAPER = "#FFFFFF"
NIGHT = "#0E1014"    # тёмный фон сайта

WORD = "podslushano"
TLD = ".nl"


# ----------------------------------------------------------------- надпись в кривых

def text_paths(text: str, size: float, x0: float, baseline: float, tracking: float = -0.02) -> tuple[str, float]:
    """Возвращает (d-атрибут пути, ширина) для строки, набранной шрифтом FONT."""
    font = TTFont(FONT)
    upm = font["head"].unitsPerEm
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    scale = size / upm
    pen = SVGPathPen(gs)
    x = x0
    for ch in text:
        name = cmap[ord(ch)]
        tp = TransformPen(pen, (scale, 0, 0, -scale, x, baseline))
        gs[name].draw(tp)
        x += hmtx[name][0] * scale + tracking * size
    return pen.getCommands(), x - x0 - tracking * size


# ----------------------------------------------------------------- знаки (сетка 100x100)

def mark_replika(fg: str, accent: str) -> str:
    """«Реплика»: строчная p, у которой чаша — облачко речи, а хвост облачка — ножка буквы."""
    return (
        f'<circle cx="58" cy="42" r="23" fill="none" stroke="{accent}" stroke-width="15"/>'
        f'<path d="M27.5 26a8 8 0 0 1 16 0V71L27.5 89Z" fill="{fg}"/>'
    )


def mark_dvenadtsat(fg: str, accent: str) -> str:
    """«Двенадцать»: облачко речи из 12 сегментов, по числу провинций; один сегмент выделен."""
    cx, cy, r, w = 52, 46, 31, 11
    parts = []
    gap = 4.2  # градусы между сегментами
    for i in range(12):
        a0 = -90 + i * 30 + gap / 2
        a1 = -90 + (i + 1) * 30 - gap / 2
        x0, y0 = cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0))
        x1, y1 = cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1))
        col = accent if i == 1 else fg
        parts.append(
            f'<path d="M{x0:.2f} {y0:.2f}A{r} {r} 0 0 1 {x1:.2f} {y1:.2f}" fill="none" '
            f'stroke="{col}" stroke-width="{w}" stroke-linecap="butt"/>'
        )
    # хвост облачка
    parts.append(f'<path d="M24 62L13 92L42 74Z" fill="{fg}"/>')
    return "".join(parts)


def mark_kavychki(fg: str, accent: str) -> str:
    """«Кавычки»: облачко речи с русскими кавычками «» — то, что сказано по-русски."""
    chev = "".join(f'<path d="M{x + 9} 31L{x} 44L{x + 9} 57"/>' for x in (24, 36)) + \
        "".join(f'<path d="M{x} 31L{x + 9} 44L{x} 57"/>' for x in (55, 67))
    return (
        f'<path d="M22 12H78A14 14 0 0 1 92 26V62A14 14 0 0 1 78 76H44L24 92V76H22A14 14 0 0 1 8 62V26A14 14 0 0 1 22 12Z" fill="{accent}"/>'
        f'<g fill="none" stroke="{fg}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round">{chev}</g>'
    )


# Ключ: (название, функция, границы знака x0, y0, x1, y1 в сетке 100x100)
MARKS = {
    "a-replika": ("Реплика", mark_replika, (27.5, 11.5, 88.5, 89)),
    "b-dvenadtsat": ("Двенадцать", mark_dvenadtsat, (13, 9.5, 88.5, 92)),
    "c-kavychki": ("Кавычки", mark_kavychki, (8, 12, 92, 92)),
}


def fit(body: str, bbox, x: float, y: float, h: float) -> tuple[str, float]:
    """Ставит знак так, чтобы его границы начинались в (x, y) и имели высоту h. Возвращает (svg, ширина)."""
    x0, y0, x1, y1 = bbox
    k = h / (y1 - y0)
    return f'<g transform="translate({x - x0 * k:.2f} {y - y0 * k:.2f}) scale({k:.4f})">{body}</g>', (x1 - x0) * k


# ----------------------------------------------------------------- сборка файлов

def svg(w: float, h: float, body: str, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" height="{h:.0f}" role="img">'
        f"<title>{title}</title>{body}</svg>\n"
    )


def wordmark(fg: str, accent: str, x: float, baseline: float, size: float) -> tuple[str, float]:
    d1, w1 = text_paths(WORD, size, x, baseline)
    d2, w2 = text_paths(TLD, size, x + w1 + 0.0 * size, baseline)
    return f'<path d="{d1}" fill="{fg}"/><path d="{d2}" fill="{accent}"/>', w1 + w2


def build() -> None:
    size = 64                       # кегль надписи
    cap = size * 0.70               # высота строчных с выносными (p, d, l) — ориентир для знака
    mark_h = 84                     # высота знака в горизонтальной версии
    gap = 20                        # расстояние знак — надпись
    pad = 8                         # охранное поле внутри файла
    for key, (label, fn, bbox) in MARKS.items():
        d = OUT / key
        d.mkdir(parents=True, exist_ok=True)
        for theme, fg in (("light", INK), ("dark", PAPER)):
            m, mw = fit(fn(fg, ACCENT), bbox, 0, 0, 100)
            (d / f"mark-{theme}.svg").write_text(svg(mw, 100, m, f"podslushano.nl, знак «{label}»"))
            # горизонтальная версия: знак слева, надпись по центру высоты знака
            words, ww = wordmark(fg, ACCENT, 0, 0, size)
            m, mw = fit(fn(fg, ACCENT), bbox, pad, pad, mark_h)
            base = pad + mark_h / 2 + size * 0.26   # базовая линия: x-высота по центру знака
            body = m + f'<g transform="translate({pad + mw + gap:.2f} {base:.2f})">{words}</g>'
            (d / f"logo-horizontal-{theme}.svg").write_text(svg(pad + mw + gap + ww + pad, mark_h + 2 * pad, body, "podslushano.nl"))
            # вертикальная версия: знак над надписью
            vh = 120
            vw = max(ww, 120) + 2 * pad
            m, mw = fit(fn(fg, ACCENT), bbox, 0, pad, vh)
            m, mw = fit(fn(fg, ACCENT), bbox, (vw - mw) / 2, pad, vh)
            body = m + f'<g transform="translate({(vw - ww) / 2:.2f} {pad + vh + 28 + size * 0.74:.2f})">{words}</g>'
            (d / f"logo-vertical-{theme}.svg").write_text(svg(vw, pad + vh + 28 + size + pad, body, "podslushano.nl"))
        # иконки приложения 1024x1024 (углы скругляет система); знак занимает около 60 % высоты
        for name, bg, fg, ac in (("app-icon", ACCENT, PAPER, PAPER if key == "a-replika" else INK),
                                 ("app-icon-dark", NIGHT, PAPER, ACCENT)):
            x0, y0, x1, y1 = bbox
            h = 600
            w = (x1 - x0) * h / (y1 - y0)
            m, _ = fit(fn(fg, ac), bbox, (1024 - w) / 2, (1024 - h) / 2, h)
            (d / f"{name}.svg").write_text(svg(1024, 1024, f'<rect width="1024" height="1024" fill="{bg}"/>' + m, "podslushano.nl"))
    # надпись без знака — общая для всех вариантов
    for theme, fg in (("light", INK), ("dark", PAPER)):
        words, ww = wordmark(fg, ACCENT, pad, pad + size * 0.74, size)
        (OUT / f"wordmark-{theme}.svg").write_text(svg(ww + 2 * pad, size * 0.98 + 2 * pad, words, "podslushano.nl"))
    print("готово:", OUT)


if __name__ == "__main__":
    build()
