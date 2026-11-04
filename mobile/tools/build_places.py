"""Собирает базу мест для раздела «Места».

Источники:
- OpenStreetMap через Overpass API (лицензия ODbL, нужна подпись «© участники OpenStreetMap»):
  музеи, замки и крепости, парки и природа, пляжи, мельницы, места для детей —
  с часами работы, сайтом, телефоном и ценой, если они указаны;
- Wikidata (CC0) для мест со ссылкой на неё: фото с Wikimedia Commons, русское название и описание.

Название места — нидерландское, латиницей, как в бренд-буке.

Запуск из папки mobile:  python3 tools/build_places.py
Результат: src/data/places.json
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "data" / "places.json"
UA = "podslushano-app-data/1.0 (https://www.podslushano.nl)"
OVERPASS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

PROVINCES = {
    "gr": "NL-GR", "fr": "NL-FR", "dr": "NL-DR", "ov": "NL-OV", "fl": "NL-FL", "ge": "NL-GE",
    "ut": "NL-UT", "nh": "NL-NH", "zh": "NL-ZH", "ze": "NL-ZE", "nb": "NL-NB", "li": "NL-LI",
}
LIMIT = {"museum": 60, "castle": 30, "nature": 40, "beach": 25, "windmill": 25, "kids": 30}

QUERY = """[out:json][timeout:180];
area["ISO3166-2"="{iso}"]->.a;
(
  nwr["tourism"="museum"]["name"](area.a);
  nwr["historic"~"^(castle|fort)$"]["name"](area.a);
  nwr["boundary"="national_park"]["name"](area.a);
  nwr["leisure"~"^(park|nature_reserve)$"]["name"]["wikidata"](area.a);
  nwr["natural"="beach"]["name"](area.a);
  nwr["man_made"="windmill"]["name"]["wikidata"](area.a);
  nwr["tourism"~"^(zoo|theme_park|aquarium)$"]["name"](area.a);
  nwr["leisure"="water_park"]["name"](area.a);
);
out center tags;"""


def http(url: str, data: bytes | None = None, timeout: int = 200) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def overpass(iso: str) -> list[dict]:
    body = urllib.parse.urlencode({"data": QUERY.format(iso=iso)}).encode()
    for attempt in range(6):
        url = OVERPASS[attempt % len(OVERPASS)]
        try:
            return json.loads(http(url, body))["elements"]
        except Exception as e:  # перегрузка зеркала — пробуем следующее
            print("  повтор", url.split("/")[2], e, flush=True)
            time.sleep(10)
    raise RuntimeError("Overpass не отвечает")


def kind_of(t: dict) -> str | None:
    if t.get("tourism") in ("zoo", "theme_park", "aquarium") or t.get("leisure") == "water_park":
        return "kids"
    if t.get("tourism") == "museum":
        return "museum"
    if t.get("historic") in ("castle", "fort"):
        return "castle"
    if t.get("man_made") == "windmill":
        return "windmill"
    if t.get("natural") == "beach":
        return "beach"
    if t.get("boundary") == "national_park" or t.get("leisure") in ("park", "nature_reserve"):
        return "nature"
    return None


def score(t: dict) -> int:
    """Чем больше о месте известно, тем оно заметнее: выше в списке."""
    return (5 * bool(t.get("wikidata")) + 3 * bool(t.get("wikipedia")) + 2 * bool(t.get("website") or t.get("contact:website"))
            + 2 * bool(t.get("opening_hours")) + bool(t.get("image") or t.get("wikimedia_commons")))


def commons(file: str) -> str:
    name = file.removeprefix("File:").removeprefix("Файл:")
    return "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(name.replace(" ", "_")) + "?width=800"


def enrich(places: list[dict]) -> None:
    """Фото, русское название и описание из Wikidata — пачками по 50 мест."""
    ids = [p["wd"] for p in places if p["wd"]]
    info: dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        chunk = "|".join(ids[i:i + 50])
        url = ("https://www.wikidata.org/w/api.php?action=wbgetentities&props=claims|labels|descriptions"
               f"&languages=ru&format=json&ids={chunk}")
        for _ in range(4):
            try:
                info.update(json.loads(http(url, timeout=60)).get("entities", {}))
                break
            except Exception as e:
                print("  повтор wikidata", e, flush=True)
                time.sleep(15)
        time.sleep(1)
    for p in places:
        e = info.get(p["wd"]) or {}
        p["ru"] = e.get("labels", {}).get("ru", {}).get("value", "")
        p["desc"] = e.get("descriptions", {}).get("ru", {}).get("value", "")
        img = (e.get("claims", {}).get("P18") or [{}])[0].get("mainsnak", {}).get("datavalue", {}).get("value")
        if img and not p["img"]:
            p["img"] = commons(img)


def build() -> None:
    places: list[dict] = []
    seen: set[str] = set()
    for pid, iso in PROVINCES.items():
        elements = overpass(iso)
        by_kind: dict[str, list[dict]] = {}
        for el in elements:
            t = el.get("tags", {})
            k = kind_of(t)
            name = t.get("name", "").strip()
            if not k or not name:
                continue
            # у замков и крепостей много мелких руин и частных усадеб: оставляем известные или с сайтом
            if k == "castle" and not (t.get("wikidata") or t.get("website") or t.get("tourism")):
                continue
            key = (t.get("wikidata") or f"{name}|{k}").lower()
            if key in seen:
                continue
            seen.add(key)
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")
            if lat is None:
                continue
            img = t.get("image", "") if t.get("image", "").startswith("https://") else ""
            if not img and t.get("wikimedia_commons", "").startswith("File:"):
                img = commons(t["wikimedia_commons"])
            by_kind.setdefault(k, []).append({
                "id": f"{el['type'][0]}{el['id']}", "name": name, "ru": "", "desc": "", "kinds": [k], "province": pid,
                "town": t.get("addr:city", ""), "street": " ".join(x for x in (t.get("addr:street", ""), t.get("addr:housenumber", "")) if x),
                "lat": round(float(lat), 5), "lon": round(float(lon), 5),
                "site": t.get("website") or t.get("contact:website") or "", "phone": t.get("phone") or t.get("contact:phone") or "",
                "hours": t.get("opening_hours", ""), "fee": t.get("charge") or ("бесплатно" if t.get("fee") == "no" else ""),
                "img": img, "wd": t.get("wikidata", ""), "rank": score(t),
            })
        counts = {}
        for k, lst in by_kind.items():
            lst.sort(key=lambda p: -p["rank"])
            places += lst[:LIMIT[k]]
            counts[k] = min(len(lst), LIMIT[k])
        print(pid, "объектов:", len(elements), "взято:", counts, flush=True)
        time.sleep(5)
    enrich(places)
    for p in places:
        p["rank"] += 3 * bool(p["img"])
        del p["wd"]
    places.sort(key=lambda p: (p["province"], -p["rank"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "© участники OpenStreetMap (ODbL), Wikidata, фото Wikimedia Commons",
                               "built": time.strftime("%Y-%m-%d"), "places": places}, ensure_ascii=False, separators=(",", ":")))
    print("всего мест:", len(places), "с фото:", sum(bool(p["img"]) for p in places),
          "с часами:", sum(bool(p["hours"]) for p in places), "файл:", round(OUT.stat().st_size / 1024), "КБ")


if __name__ == "__main__":
    build()
