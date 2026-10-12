"""Фирменное оформление всех писем podslushano.nl.

render_email() собирает письмо: прехедер, шапка с логотипом (или лосёнком),
заголовок, блоки текста, кнопка, подвал с соцсетями и отпиской. Вёрстка на
таблицах и inline-стилях — так письмо одинаково выглядит в Gmail, Outlook и Apple Mail.
Картинки — PNG с сервера бота (/email-assets/), WebP почтовики показывают не везде.

wrap_legacy() оборачивает старые «голые» письма, поэтому любое письмо, ушедшее
через utils.invoices.send_email_message, получает фирменный вид автоматически.
"""
from __future__ import annotations

import html
import re

import config

MARK = "<!--pn-brand-->"
INK, TEXT, MUTED, LINE, BG, ACC = "#0D1117", "#2E3540", "#6A7280", "#E2E5EA", "#F4F5F7", "#FF5A1F"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
SOCIAL = [
    ("instagram", "Instagram", "https://www.instagram.com/podslushano.nl"),
    ("telegram", "Telegram", "https://t.me/podslushanovnl"),
    ("facebook", "Facebook", "https://www.facebook.com/podslushano.nl"),
    ("tiktok", "TikTok", "https://www.tiktok.com/@podslushano.nl"),
    ("youtube", "YouTube", "https://www.youtube.com/@podslushanonl"),
]


def asset(name: str) -> str:
    base = (config.WEBHOOK_BASE_URL or "https://worker-production-ad76.up.railway.app").rstrip("/")
    return f"{base}/email-assets/{name}"


def site(path: str = "") -> str:
    return (config.SITE_URL or "https://www.podslushano.nl").rstrip("/") + path


def esc(text) -> str:
    return html.escape(str(text or ""), quote=True)


# ---------------------------------------------------------------- блоки

def p(text_html: str) -> str:
    return (f'<p style="margin:0 0 16px;font:400 16px/1.6 {FONT};color:{TEXT};">{text_html}</p>')


def bullets(items: list[str]) -> str:
    rows = "".join(
        f'<tr><td valign="top" style="padding:4px 12px 8px 0;width:10px;">'
        f'<div style="width:8px;height:8px;border-radius:4px;background:{ACC};margin-top:8px;"></div></td>'
        f'<td style="padding:0 0 8px;font:400 16px/1.55 {FONT};color:{TEXT};">{it}</td></tr>' for it in items)
    return f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 16px;">{rows}</table>'


def steps(items: list[tuple[str, str]]) -> str:
    rows = "".join(
        f'<tr><td valign="top" style="padding:0 14px 14px 0;width:28px;">'
        f'<div style="width:28px;height:28px;border-radius:14px;background:{INK};color:#fff;'
        f'font:700 14px/28px {FONT};text-align:center;">{i}</div></td>'
        f'<td style="padding:2px 0 14px;font:400 15px/1.5 {FONT};color:{TEXT};">'
        f'<b style="color:{INK};">{t}</b><br>{d}</td></tr>' for i, (t, d) in enumerate(items, 1))
    return f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:4px 0 12px;">{rows}</table>'


def box(inner_html: str, tone: str = "soft") -> str:
    bg = {"soft": BG, "warm": "#FFF1E8", "ok": "#EAF7EF"}.get(tone, BG)
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:4px 0 18px;">'
            f'<tr><td style="background:{bg};border-radius:16px;padding:16px 18px;font:400 15px/1.55 {FONT};color:{TEXT};">'
            f'{inner_html}</td></tr></table>')


def facts(rows: list[tuple[str, str]]) -> str:
    tr = "".join(
        f'<tr><td style="padding:8px 0;border-bottom:1px solid {LINE};font:400 14px/1.4 {FONT};color:{MUTED};">{k}</td>'
        f'<td align="right" style="padding:8px 0;border-bottom:1px solid {LINE};font:600 14px/1.4 {FONT};color:{INK};">{v}</td></tr>'
        for k, v in rows)
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 18px;">{tr}</table>'


def small(text_html: str) -> str:
    return f'<p style="margin:0 0 12px;font:400 13px/1.55 {FONT};color:{MUTED};">{text_html}</p>'


def button(label: str, url: str) -> str:
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 22px;"><tr>'
            f'<td align="center" bgcolor="{ACC}" style="border-radius:999px;background:{ACC};">'
            f'<a href="{esc(url)}" target="_blank" style="display:inline-block;padding:15px 30px;font:700 16px/1 {FONT};'
            f'color:#ffffff;text-decoration:none;border-radius:999px;">{esc(label)}</a></td></tr></table>')


# ---------------------------------------------------------------- письмо целиком

def render_email(*, title: str = "", preheader: str = "", eyebrow: str = "", body: str = "",
                 cta: tuple[str, str] | None = None, after_cta: str = "", hero: str = "logo",
                 reason: str = "", unsubscribe_url: str | None = None) -> str:
    """Собирает HTML письма. body — HTML из блоков p()/bullets()/box()/…"""
    hero_img = (
        f'<img src="{asset("deer.png")}" width="96" alt="Лосёнок podslushano.nl" style="display:block;margin:0 auto;border:0;">'
        if hero == "deer" else
        f'<img src="{asset("logo.png")}" width="200" alt="podslushano.nl" style="display:block;margin:0 auto;border:0;">')
    head = (f'<tr><td align="center" style="padding:28px 28px 8px;">'
            f'<a href="{site()}" target="_blank" style="text-decoration:none;">{hero_img}</a></td></tr>')
    eb = (f'<div style="font:700 12px/1 {FONT};letter-spacing:.08em;text-transform:uppercase;color:{ACC};margin:0 0 10px;">'
          f'{esc(eyebrow)}</div>') if eyebrow else ""
    h1 = (f'<h1 style="margin:0 0 16px;font:800 28px/1.15 {FONT};letter-spacing:-.02em;color:{INK};">{title}</h1>'
          if title else "")
    cta_html = button(*cta) if cta else ""
    icons = "".join(
        f'<td style="padding:0 6px;"><a href="{u}" target="_blank" title="{n}">'
        f'<img src="{asset(k + ".png")}" width="32" height="32" alt="{n}" style="display:block;border:0;"></a></td>'
        for k, n, u in SOCIAL)
    unsub = (f' · <a href="{esc(unsubscribe_url)}" style="color:{MUTED};text-decoration:underline;">Отписаться</a>'
             if unsubscribe_url else "")
    reason_html = esc(reason) if reason else "Вы получили это письмо, потому что пользуетесь сервисами podslushano.nl."
    pre = (f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{esc(preheader)}'
           + "&nbsp;&zwnj;" * 40 + "</div>") if preheader else ""
    return f"""<!doctype html>{MARK}
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only"><meta name="supported-color-schemes" content="light">
<title>{esc(re.sub(r"<[^>]+>", "", title) or "podslushano.nl")}</title></head>
<body style="margin:0;padding:0;background:{BG};">{pre}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{BG};">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;background:#ffffff;border-radius:24px;overflow:hidden;">
{head}
<tr><td style="padding:16px 32px 12px;">{eb}{h1}{body}{cta_html}{after_cta}</td></tr>
</table>
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;">
<tr><td align="center" style="padding:24px 16px 8px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>{icons}</tr></table></td></tr>
<tr><td align="center" style="padding:8px 24px 4px;font:600 14px/1.5 {FONT};color:{INK};">
<a href="{site()}" target="_blank" style="color:{INK};text-decoration:none;">podslushano.nl</a> · жизнь в Нидерландах по-русски</td></tr>
<tr><td align="center" style="padding:4px 24px 28px;font:400 12px/1.6 {FONT};color:{MUTED};">
{reason_html}{unsub}<br>{esc(config.COMPANY_NAME)} · {esc(config.COMPANY_EMAIL)}</td></tr>
</table>
</td></tr></table></body></html>"""


def text_version(title: str, paragraphs: list[str], cta: tuple[str, str] | None = None,
                 unsubscribe_url: str | None = None) -> str:
    """Текстовая версия письма (для почтовиков без HTML и для антиспам-фильтров)."""
    clean = [re.sub(r"<[^>]+>", "", html.unescape(x)).strip() for x in [title, *paragraphs]]
    out = "\n\n".join(x for x in clean if x)
    if cta:
        out += f"\n\n{cta[0]}: {cta[1]}"
    out += f"\n\n—\npodslushano.nl · {site()}"
    if unsubscribe_url:
        out += f"\nОтписаться: {unsubscribe_url}"
    return out


def wrap_legacy(html_body: str, subject: str = "") -> str:
    """Старое письмо без оформления → фирменная рамка вокруг того же текста."""
    if MARK in html_body or "<html" in html_body[:400].lower():
        return html_body
    styled = re.sub(r"<p>", f'<p style="margin:0 0 16px;font:400 16px/1.6 {FONT};color:{TEXT};">', html_body)
    styled = re.sub(r"<a (?![^>]*style=)", f'<a style="color:{ACC};font-weight:600;" ', styled)
    return render_email(title="", preheader=re.sub(r"\s*·\s*podslushano\.nl$", "", subject), body=styled)
