"""Финальный логотип podslushano.nl — «Мельница» (выбран 4 ноября 2026).

Собирает SVG в brand/logo/final/ и PNG-файлы иконок приложения в mobile/assets/images/.
PNG рисует Chromium (Playwright), поэтому нужен node с пакетом playwright.

Запуск из корня репозитория:  python3 brand/tools/build_logo_final.py
"""
from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from pathlib import Path

from build_logo_v2 import INK, NIGHT, PAPER, defs, fit, mark_melnitsa, svg, wordmark

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
OUT = ROOT / "logo" / "final"
APP = REPO / "mobile" / "assets" / "images"

BBOX = (5, 5, 95, 95)
CREAM = "#FFF6EF"   # фон иконки приложения: тёплый светлый, знак на нём яркий


def mark(uid: str, mono: str | None = None) -> str:
    return (defs(uid) if not mono else "") + mark_melnitsa(uid, mono)


def build_svgs() -> dict[str, str]:
    OUT.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    size, mark_h, gap, pad = 64, 88, 18, 8
    for theme, fg in (("light", INK), ("dark", PAPER)):
        uid = f"f{theme[0]}"
        words, ww = wordmark(fg, 0, 0, size)
        m, mw = fit(mark(uid), BBOX, pad, pad, mark_h)
        base = pad + mark_h / 2 + size * 0.25
        files[f"logo-horizontal-{theme}.svg"] = svg(pad + mw + gap + ww + pad, mark_h + 2 * pad,
                                                    m + f'<g transform="translate({pad + mw + gap:.2f} {base:.2f})">{words}</g>', "podslushano.nl")
        vh = 132
        vw = max(ww, vh) + 2 * pad
        m, _ = fit(mark(uid + "v"), BBOX, (vw - vh) / 2, pad, vh)
        files[f"logo-vertical-{theme}.svg"] = svg(vw, pad + vh + 26 + size + pad,
                                                  m + f'<g transform="translate({(vw - ww) / 2:.2f} {pad + vh + 26 + size * 0.76:.2f})">{words}</g>', "podslushano.nl")
        words, ww = wordmark(fg, pad, pad + size * 0.76, size)
        files[f"wordmark-{theme}.svg"] = svg(ww + 2 * pad, size + 2 * pad, words, "podslushano.nl")
    m, _ = fit(mark("fm"), BBOX, 0, 0, 100)
    files["mark.svg"] = svg(100, 100, m, "podslushano.nl")
    for name, col in (("mark-mono-black.svg", INK), ("mark-mono-white.svg", PAPER)):
        m, _ = fit(mark("", mono=col), BBOX, 0, 0, 100)
        files[name] = svg(100, 100, m, "podslushano.nl")
    # иконка приложения: знак занимает 62 % плитки
    m, _ = fit(mark("fi"), BBOX, 194, 194, 636)
    files["app-icon.svg"] = svg(1024, 1024, f'<rect width="1024" height="1024" fill="{CREAM}"/>' + m, "podslushano.nl")
    m, _ = fit(mark("fd"), BBOX, 194, 194, 636)
    files["app-icon-dark.svg"] = svg(1024, 1024, f'<rect width="1024" height="1024" fill="{NIGHT}"/>' + m, "podslushano.nl")
    for k, v in files.items():
        (OUT / k).write_text(v)
    return files


def app_pngs() -> list[tuple[str, int, str, bool]]:
    """(путь, сторона, svg, прозрачный фон)."""
    out = []
    def tile(px: float, bg: str | None, mono: str | None = None, uid: str = "a") -> str:
        x = (1024 - px) / 2
        m, _ = fit(mark(uid, mono), BBOX, x, x, px)
        return svg(1024, 1024, (f'<rect width="1024" height="1024" fill="{bg}"/>' if bg else "") + m, "podslushano.nl")
    out.append((str(APP / "icon.png"), 1024, tile(636, CREAM, uid="i"), False))
    out.append((str(APP / "android-icon-background.png"), 1024, svg(1024, 1024, f'<rect width="1024" height="1024" fill="{CREAM}"/>', ""), False))
    # Android: безопасная зона адаптивной иконки — круг 66 % холста, знак внутри неё
    out.append((str(APP / "android-icon-foreground.png"), 1024, tile(560, None, uid="g"), True))
    out.append((str(APP / "android-icon-monochrome.png"), 1024, tile(560, None, mono=PAPER), True))
    out.append((str(APP / "splash-icon.png"), 1024, tile(900, None, uid="s"), True))
    out.append((str(APP / "favicon.png"), 196, tile(700, CREAM, uid="v"), False))
    out.append((str(REPO / "mobile" / "public" / "apple-touch-icon.png"), 180, tile(636, CREAM, uid="t"), False))
    return out


def render(jobs: list[tuple[str, int, str, bool]]) -> None:
    with tempfile.TemporaryDirectory() as d:
        spec = []
        for i, (path, side, s, transparent) in enumerate(jobs):
            uri = "data:image/svg+xml;base64," + base64.b64encode(s.encode()).decode()
            spec.append({"svg": uri, "out": path, "side": side, "transparent": transparent})
        js = Path(d) / "r.js"
        js.write_text(
            "const {chromium}=require('playwright');const jobs=" + json.dumps(spec) + ";"
            "(async()=>{const b=await chromium.launch();for(const j of jobs){"
            "const p=await b.newPage({viewport:{width:j.side,height:j.side},deviceScaleFactor:1});"
            "await p.setContent(`<html><body style='margin:0;background:transparent'><img src='${j.svg}' style='width:${j.side}px;height:${j.side}px;display:block'></body></html>`);"
            "await p.waitForTimeout(150);await p.screenshot({path:j.out,omitBackground:j.transparent});await p.close();}"
            "await b.close();})();")
        subprocess.run(["node", str(js)], check=True)


def flatten(path: str) -> None:
    """iOS требует иконку без прозрачности."""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.save(path)


if __name__ == "__main__":
    build_svgs()
    jobs = app_pngs()
    render(jobs)
    for path, _, _, transparent in jobs:
        if not transparent:
            flatten(path)
    print("готово:", OUT, "и", APP)
