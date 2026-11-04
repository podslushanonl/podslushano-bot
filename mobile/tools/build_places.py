"""Собирает базу мест для раздела «Места» из Wikidata (лицензия CC0), фото — Wikimedia Commons.

Для каждой из 12 провинций: музеи, замки и крепости, парки и природа, пляжи, мельницы, места для детей.
Название — нидерландское (латиницей, как в бренд-буке), описание — русское, если оно есть в Wikidata.

Запросы лёгкие (без рекурсии по административному делению): место → его муниципалитет или
населённый пункт → провинция определяется по таблице муниципалитетов. Сервис Wikidata ограничивает
частоту запросов, поэтому между ними пауза в минуту: вся сборка занимает около 8 минут.

Запуск из папки mobile:  python3 tools/build_places.py
Результат: src/data/places.json
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "data" / "places.json"
UA = "podslushano-app-data/1.0 (https://www.podslushano.nl)"

PROVINCES = {
    "gr": "Q752", "fr": "Q770", "dr": "Q772", "ov": "Q773", "fl": "Q707", "ge": "Q775",
    "ut": "Q776", "nh": "Q701", "zh": "Q694", "ze": "Q705", "nb": "Q1101", "li": "Q1093",
}

# тип места → (классы Wikidata, минимум ссылок на Википедии — отсекает совсем малоизвестное, лимит на провинцию)
KINDS = {
    "museum": (["Q33506", "Q207694", "Q1007870", "Q2772772", "Q588140", "Q17431399"], 1, 60),  # музеи разных видов
    "castle": (["Q23413", "Q57821", "Q751876", "Q1785071", "Q16748868"], 1, 30),            # замки, крепости
    "nature": (["Q46169", "Q22698", "Q167346", "Q179049", "Q473972"], 2, 40),               # нацпарки, парки, ботсады
    "beach": (["Q40080"], 1, 25),                                                           # пляжи
    "windmill": (["Q38720", "Q2593734", "Q1415899", "Q14954913"], 2, 25),                   # мельницы
    "kids": (["Q43501", "Q194195", "Q2281788", "Q1144661", "Q2416723"], 1, 30),             # зоопарки, парки развлечений
}

MUNI_QUERY = """
SELECT ?m ?prov ?label WHERE {
  ?m wdt:P31 wd:Q2039348 ; wdt:P131 ?prov .
  OPTIONAL { ?m rdfs:label ?label FILTER(LANG(?label) = "nl") }
}
"""


def query(classes: list[str], min_links: int) -> str:
    vals = " ".join(f"wd:{c}" for c in classes)
    return f"""
SELECT ?item ?loc ?loc2 ?nl ?en ?ru ?descRu ?coord ?site ?img ?links WHERE {{
  VALUES ?cls {{ {vals} }}
  ?item wdt:P31 ?cls ;
        wdt:P17 wd:Q55 ;
        wdt:P625 ?coord ;
        wdt:P131 ?loc ;
        wikibase:sitelinks ?links .
  FILTER(?links >= {min_links})
  FILTER NOT EXISTS {{ ?item wdt:P576 ?closed }}
  OPTIONAL {{ ?loc wdt:P131 ?loc2 }}
  OPTIONAL {{ ?item rdfs:label ?nl FILTER(LANG(?nl) = "nl") }}
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item rdfs:label ?ru FILTER(LANG(?ru) = "ru") }}
  OPTIONAL {{ ?item schema:description ?descRu FILTER(LANG(?descRu) = "ru") }}
  OPTIONAL {{ ?item wdt:P856 ?site }}
  OPTIONAL {{ ?item wdt:P18 ?img }}
}}
"""


def sparql(q: str) -> list[dict]:
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": q, "format": "json"})
    for _ in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)["results"]["bindings"]
        except Exception as e:  # перегрузка или ограничение частоты — ждём минуту и повторяем
            print("  повтор:", e, flush=True)
            time.sleep(65)
    raise RuntimeError("Wikidata не отвечает")


def qid(v: dict | None) -> str:
    return v["value"].rsplit("/", 1)[-1] if v else ""


def point(wkt: str) -> tuple[float, float]:
    lon, lat = re.findall(r"[-\d.]+", wkt)[:2]
    return round(float(lat), 5), round(float(lon), 5)


def image(url: str | None) -> str:
    if not url:
        return ""
    name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
    return "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(name) + "?width=800"


def build() -> None:
    by_q = {q: pid for pid, q in PROVINCES.items()}
    muni: dict[str, tuple[str, str]] = {}   # муниципалитет → (провинция, название)
    for r in sparql(MUNI_QUERY):
        if qid(r["prov"]) in by_q:
            muni[qid(r["m"])] = (by_q[qid(r["prov"])], r.get("label", {}).get("value", ""))
    print("муниципалитетов:", len(muni), flush=True)

    places: dict[str, dict] = {}
    for kind, (classes, min_links, limit) in KINDS.items():
        time.sleep(65)  # не чаще одного запроса в минуту
        rows = sorted(sparql(query(classes, min_links)), key=lambda r: -int(r["links"]["value"]))
        count: dict[str, int] = {}
        for r in rows:
            q = qid(r["item"])
            loc, loc2 = qid(r.get("loc")), qid(r.get("loc2"))
            hit = muni.get(loc) or muni.get(loc2) or ((by_q[loc], "") if loc in by_q else None)
            if not hit:
                continue
            pid, town = hit
            name = (r.get("nl") or r.get("en") or {}).get("value", "")
            if not name or re.fullmatch(r"Q\d+", name):
                continue
            if q in places:   # дубль строки (другое фото, метка) или то же место другого типа — дополняем
                p = places[q]
                if kind not in p["kinds"]:
                    p["kinds"].append(kind)
                for f, k in (("site", "site"), ("desc", "descRu"), ("ru", "ru")):
                    if not p[f] and r.get(k):
                        p[f] = r[k]["value"]
                if not p["img"] and r.get("img"):
                    p["img"] = image(r["img"]["value"])
                continue
            if count.get(pid, 0) >= limit:
                continue
            lat, lon = point(r["coord"]["value"])
            places[q] = {
                "id": q, "name": name, "ru": r.get("ru", {}).get("value", ""), "desc": r.get("descRu", {}).get("value", ""),
                "kinds": [kind], "province": pid, "town": town, "street": "", "lat": lat, "lon": lon,
                "site": r.get("site", {}).get("value", ""), "phone": "", "hours": "", "fee": "",
                "img": image(r.get("img", {}).get("value")), "rank": int(r["links"]["value"]),
            }
            count[pid] = count.get(pid, 0) + 1
        print(kind, "строк:", len(rows), "по провинциям:", dict(sorted(count.items())), flush=True)

    data = sorted(places.values(), key=lambda p: (p["province"], -(p["rank"] + 5 * bool(p["img"]))))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "Wikidata (CC0), фото Wikimedia Commons", "built": time.strftime("%Y-%m-%d"),
                               "places": data}, ensure_ascii=False, separators=(",", ":")))
    print("всего мест:", len(data), "с фото:", sum(bool(p["img"]) for p in data), "файл:", round(OUT.stat().st_size / 1024), "КБ")


if __name__ == "__main__":
    build()
