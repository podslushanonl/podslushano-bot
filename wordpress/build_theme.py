#!/usr/bin/env python3
"""Builds the WordPress theme podslushano-2026 from wordpress/src.

Output: wordpress/theme/podslushano-2026/{assets,shell.php,links.html,data/*}
and wordpress/dist/podslushano-2026.zip (upload in WordPress: Внешний вид → Темы → Добавить → Загрузить).
"""
import json
import os
import re
import shutil
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'src')
THEME = os.path.join(ROOT, 'theme', 'podslushano-2026')
A = '/wp-content/themes/podslushano-2026/assets/'


def rd(*p):
    return open(os.path.join(SRC, *p), encoding='utf-8').read()


def build_app():
    s = rd('app.src.html')
    imgs = sorted(os.listdir(os.path.join(SRC, 'img')))
    by_name = {f.rsplit('.', 1)[0]: f for f in imgs}
    imap = {k: A + 'img/' + v for k, v in by_name.items()}
    si = json.loads(rd('data', 'si.json'))
    ranges = json.loads(rd('fonts', 'mont_ranges.json'))
    rep = {
        '{{IMGS}}': json.dumps(imap),
        '{{DEER}}': A + 'img/deer.webp', '{{GROUP}}': A + 'img/group.jpg', '{{CANAL}}': A + 'img/cta.jpg',
        '{{DATA4}}': rd('data', 'events_bundle.json'), '{{SPEC}}': rd('data', 'spec11.json'),
        '{{PROV}}': rd('data', 'prov2.json'), '{{NEWS}}': rd('data', 'news.json'),
        '{{NEWSF}}': rd('data', 'news_full.json'), '{{JOBS11}}': rd('data', 'jobs11.json'),
        '{{SI}}': json.dumps(si),
    }
    for k, v in rep.items():
        s = s.replace(k, v)
    s = re.sub(r'\{\{IMG:([\w-]+)\}\}', lambda m: imap[m.group(1)], s)
    s = re.sub(r'\{\{IV:([\w-]+)\}\}', lambda m: imap['iv-' + m.group(1)], s)
    s = re.sub(r'\{\{FONT9?:([\w-]+)\}\}', lambda m: A + 'fonts/' + m.group(1) + '.woff2', s)
    s = re.sub(r'\{\{MR:([\w-]+)\}\}', lambda m: ranges[m.group(1)], s)
    s = re.sub(r'\{\{SL:(\w+)\}\}', lambda m: f'<svg class="sl" viewBox="0 0 24 24" aria-hidden="true"><path d="{si[m.group(1)]}"/></svg>', s)
    s = s.replace("src:'media/", "src:'" + A + "media/").replace("`media/", "`" + A + "media/")
    s = s.replace("img:'media/", "img:'" + A + "media/").replace("='media/", "='" + A + "media/")
    left = re.findall(r'\{\{[A-Z0-9_]+(?::[\w-]+)?\}\}', s)
    assert not left, left[:5]
    css = s[s.index('<style>') + 7:s.index('</style>')]
    css = re.sub(r'@font-face\{font-family:"(?:Inter|DM Sans)";[^}]*\}', '', css)
    main_start = s.rindex('<script>')
    body = s[s.index('</style>') + 8:main_start]
    js = s[main_start + 8:s.rindex('</script>')]
    os.makedirs(os.path.join(THEME, 'assets'), exist_ok=True)
    open(os.path.join(THEME, 'assets', 'app.css'), 'w', encoding='utf-8').write(css)
    open(os.path.join(THEME, 'assets', 'app.js'), 'w', encoding='utf-8').write(js)
    open(os.path.join(THEME, 'shell.php'), 'w', encoding='utf-8').write(
        "<?php if (!defined('ABSPATH')) exit; ?>\n" + body)


def build_links():
    s = rd('links.src.html')
    i = s.index('const PARTNERS=[')
    j = s.index('const NEWS=')
    j = s.index(';', j) + 1
    s = s[:i] + ("const A='" + A + "';const PNL=window.PNL||{partners:[],events:[],news:[]};"
                 "const PARTNERS=PNL.partners.map(p=>({...p,img:A+p.img}));"
                 "const EVENTS=PNL.events.map(e=>({...e,img:A+e.img}));const NEWS=PNL.news;") + s[j:]
    s = s.replace("const SITE='https://www.podslushano.nl';", "const SITE=location.origin;")
    s = s.replace('href="${SITE}/news/${n.id}/"', 'href="${n.link||SITE+\'/news/\'}"')

    def asset(m):
        p = m.group(1).split('/')[-1]
        return A + 'img/' + p
    s = re.sub(r'\{\{B64:([^}]+)\}\}', asset, s)
    s = re.sub(r'\{\{FONT:([\w-]+)\}\}', lambda m: A + 'fonts/' + m.group(1) + '.woff2', s)
    si = json.loads(rd('data', 'si.json'))
    s = re.sub(r'\{\{SL:(\w+)\}\}', lambda m: f'<svg viewBox="0 0 24 24"><path d="{si[m.group(1)]}"/></svg>', s)
    s = re.sub(r'\{\{SLP:(\w+)\}\}', lambda m: f'<path d="{si[m.group(1)]}"/>', s)
    s = s.replace('{{SLJSON}}', json.dumps(si))
    s = s.replace('<script>\n/* ==== ', '<script>/*PNL*/</script>\n<script>\n/* ==== ', 1)
    assert '/*PNL*/' in s and '{{' not in s, re.findall(r'\{\{[^}]+\}\}', s)[:3]
    open(os.path.join(THEME, 'links.html'), 'w', encoding='utf-8').write(s)


def copy_assets():
    for sub in ('img', 'fonts', 'media'):
        dst = os.path.join(THEME, 'assets', sub)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(os.path.join(SRC, sub), dst, ignore=shutil.ignore_patterns('*.json'))
    d = json.loads(rd('data', 'events_bundle.json'))
    json.dump(d['EV'], open(os.path.join(THEME, 'data', 'events.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    shutil.copy(os.path.join(SRC, 'data', 'news_full.json'), os.path.join(THEME, 'data', 'news.json'))


def zip_theme():
    os.makedirs(os.path.join(ROOT, 'dist'), exist_ok=True)
    out = os.path.join(ROOT, 'dist', 'podslushano-2026.zip')
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for base, _, files in os.walk(THEME):
            for f in files:
                p = os.path.join(base, f)
                z.write(p, os.path.relpath(p, os.path.dirname(THEME)))
    return out


if __name__ == '__main__':
    build_app()
    build_links()
    copy_assets()
    out = zip_theme()
    print(out, round(os.path.getsize(out) / 1e6, 1), 'MB')
