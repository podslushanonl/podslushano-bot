"""Собирает справочник провинций для сайта из справочника приложения.

Источник один: mobile/src/lib/provinces.ts (провинции и их города). Скрипт пишет
wordpress/theme/podslushano-2026/inc/provinces.php, чтобы сайт отдавал провинцию у событий
по тем же правилам, что и приложение. Менять города нужно в provinces.ts, потом запускать скрипт.

Запуск из корня репозитория:  python3 mobile/tools/gen_provinces_php.py
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "mobile" / "src" / "lib" / "provinces.ts"
OUT = ROOT / "wordpress" / "theme" / "podslushano-2026" / "inc" / "provinces.php"


def norm(s: str) -> str:
    """Как norm() в provinces.ts: без регистра, диакритики, «'s-» и всего, кроме латинских букв."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"^'s-", "", s)
    return re.sub(r"[^a-z]", "", s)


def php(v) -> str:
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def main() -> None:
    provinces = []
    for line in SRC.read_text().splitlines():
        line = line.strip()
        if line.startswith("{id:"):
            obj = re.sub(r"(\b(?:id|name|capital|lat|lon|short|cities)):", r'"\1":', line.rstrip(","))
            provinces.append(json.loads(obj))
    assert len(provinces) == 12, len(provinces)
    names = ",\n".join(f"        {php(p['id'])} => {php(p['name'])}" for p in provinces)
    cities = ",\n".join(f"        {php(norm(c))} => {php(p['id'])}" for p in provinces for c in p["cities"])
    OUT.write_text(f"""<?php
/* ---------- Провинции: id => название и город => провинция ----------
 * Файл собран скриптом mobile/tools/gen_provinces_php.py из mobile/src/lib/provinces.ts.
 * Не редактируйте его вручную: меняйте provinces.ts и запускайте скрипт заново. */
if (!defined('ABSPATH')) exit;

function pn_provinces() {{
    return [
{names},
    ];
}}

function pn_province_cities() {{
    return [
{cities},
    ];
}}

/* Нормализация как в приложении: без регистра, диакритики, «'s-» и всего, кроме латинских букв */
function pn_norm_city($s) {{
    $s = mb_strtolower((string) $s, 'UTF-8');
    if (class_exists('Normalizer')) $s = preg_replace('/\\p{{Mn}}/u', '', Normalizer::normalize($s, Normalizer::FORM_D));
    $s = preg_replace("/^'s-/", '', $s);
    return preg_replace('/[^a-z]/', '', $s);
}}

/* id провинции по городу ('Valkenburg' => 'li') или '' — город неизвестен */
function pn_province_of_city($city) {{
    $n = pn_norm_city($city);
    if ($n === '') return '';
    $map = pn_province_cities();
    if (isset($map[$n])) return $map[$n];
    foreach ($map as $k => $id) {{
        if (strpos($n, $k) !== false || (strlen($n) > 4 && strpos($k, $n) !== false)) return $id;
    }}
    return '';
}}
""")
    print("готово:", OUT, sum(len(p["cities"]) for p in provinces), "городов")


if __name__ == "__main__":
    main()
