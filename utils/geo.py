"""География Нидерландов и категории специалистов для умного поиска.

Здесь:
- какие города к какой провинции относятся (CITY_TO_PROVINCE);
- какие провинции соседствуют (NEIGHBORS) — чтобы предлагать специалистов
  из соседних регионов, если в нужном городе никого нет;
- категории специалистов и слова-синонимы для распознавания запроса (CATEGORIES).

Города пишем и по-русски, и по-английски/нидерландски (как люди реально пишут).
"""

import math

# --- Соседние провинции -----------------------------------------------------
NEIGHBORS: dict[str, list[str]] = {
    "Groningen": ["Friesland", "Drenthe"],
    "Friesland": ["Groningen", "Drenthe", "Overijssel", "Flevoland"],
    "Drenthe": ["Groningen", "Friesland", "Overijssel"],
    "Overijssel": ["Drenthe", "Friesland", "Flevoland", "Gelderland"],
    "Flevoland": ["Friesland", "Overijssel", "Gelderland", "Utrecht", "Noord-Holland"],
    "Gelderland": ["Overijssel", "Flevoland", "Utrecht", "Noord-Brabant", "Limburg"],
    "Utrecht": ["Flevoland", "Gelderland", "Zuid-Holland", "Noord-Holland"],
    "Noord-Holland": ["Flevoland", "Utrecht", "Zuid-Holland"],
    "Zuid-Holland": ["Noord-Holland", "Utrecht", "Gelderland", "Noord-Brabant", "Zeeland"],
    "Zeeland": ["Zuid-Holland", "Noord-Brabant"],
    "Noord-Brabant": ["Zeeland", "Zuid-Holland", "Gelderland", "Limburg"],
    "Limburg": ["Noord-Brabant", "Gelderland"],
}

# --- Города -> провинция -----------------------------------------------------
# Ключи в нижнем регистре. Значение: (каноничное_имя_города, провинция).
CITY_TO_PROVINCE: dict[str, tuple[str, str]] = {
    # Noord-Holland
    "amsterdam": ("Amsterdam", "Noord-Holland"),
    "амстердам": ("Amsterdam", "Noord-Holland"),
    "haarlem": ("Haarlem", "Noord-Holland"),
    "харлем": ("Haarlem", "Noord-Holland"),
    "alkmaar": ("Alkmaar", "Noord-Holland"),
    "алкмар": ("Alkmaar", "Noord-Holland"),
    "zaandam": ("Zaandam", "Noord-Holland"),
    "зандам": ("Zaandam", "Noord-Holland"),
    "hilversum": ("Hilversum", "Noord-Holland"),
    "хилверсюм": ("Hilversum", "Noord-Holland"),
    "amstelveen": ("Amstelveen", "Noord-Holland"),
    "амстелвен": ("Amstelveen", "Noord-Holland"),
    "hoofddorp": ("Hoofddorp", "Noord-Holland"),
    "хофддорп": ("Hoofddorp", "Noord-Holland"),
    # Zuid-Holland
    "rotterdam": ("Rotterdam", "Zuid-Holland"),
    "роттердам": ("Rotterdam", "Zuid-Holland"),
    "den haag": ("Den Haag", "Zuid-Holland"),
    "the hague": ("Den Haag", "Zuid-Holland"),
    "гаага": ("Den Haag", "Zuid-Holland"),
    "гааг": ("Den Haag", "Zuid-Holland"),  # ловит склонения: в Гааге, из Гааги
    "ден хааг": ("Den Haag", "Zuid-Holland"),
    "leiden": ("Leiden", "Zuid-Holland"),
    "лейден": ("Leiden", "Zuid-Holland"),
    "delft": ("Delft", "Zuid-Holland"),
    "делфт": ("Delft", "Zuid-Holland"),
    "dordrecht": ("Dordrecht", "Zuid-Holland"),
    "дордрехт": ("Dordrecht", "Zuid-Holland"),
    "zoetermeer": ("Zoetermeer", "Zuid-Holland"),
    "зутермер": ("Zoetermeer", "Zuid-Holland"),
    # Utrecht
    "utrecht": ("Utrecht", "Utrecht"),
    "утрехт": ("Utrecht", "Utrecht"),
    "amersfoort": ("Amersfoort", "Utrecht"),
    "амерсфорт": ("Amersfoort", "Utrecht"),
    # Noord-Brabant
    "eindhoven": ("Eindhoven", "Noord-Brabant"),
    "эйндховен": ("Eindhoven", "Noord-Brabant"),
    "tilburg": ("Tilburg", "Noord-Brabant"),
    "тилбург": ("Tilburg", "Noord-Brabant"),
    "breda": ("Breda", "Noord-Brabant"),
    "бреда": ("Breda", "Noord-Brabant"),
    "бреде": ("Breda", "Noord-Brabant"),  # «в Бреде»
    "бреды": ("Breda", "Noord-Brabant"),
    "den bosch": ("Den Bosch", "Noord-Brabant"),
    "ден бос": ("Den Bosch", "Noord-Brabant"),
    "helmond": ("Helmond", "Noord-Brabant"),
    "хелмонд": ("Helmond", "Noord-Brabant"),
    "oss": ("Oss", "Noord-Brabant"),
    "осc": ("Oss", "Noord-Brabant"),
    "осс": ("Oss", "Noord-Brabant"),
    "uden": ("Uden", "Noord-Brabant"),
    "юден": ("Uden", "Noord-Brabant"),
    "veghel": ("Veghel", "Noord-Brabant"),
    "вегел": ("Veghel", "Noord-Brabant"),
    "wijchen": ("Wijchen", "Gelderland"),
    "вейхен": ("Wijchen", "Gelderland"),
    # Limburg
    "maastricht": ("Maastricht", "Limburg"),
    "маастрихт": ("Maastricht", "Limburg"),
    "venlo": ("Venlo", "Limburg"),
    "венло": ("Venlo", "Limburg"),
    "heerlen": ("Heerlen", "Limburg"),
    "херлен": ("Heerlen", "Limburg"),
    # Gelderland
    "arnhem": ("Arnhem", "Gelderland"),
    "арнем": ("Arnhem", "Gelderland"),
    "nijmegen": ("Nijmegen", "Gelderland"),
    "неймеген": ("Nijmegen", "Gelderland"),
    "apeldoorn": ("Apeldoorn", "Gelderland"),
    "апелдорн": ("Apeldoorn", "Gelderland"),
    "ede": ("Ede", "Gelderland"),
    "эде": ("Ede", "Gelderland"),
    # Overijssel
    "zwolle": ("Zwolle", "Overijssel"),
    "зволле": ("Zwolle", "Overijssel"),
    "enschede": ("Enschede", "Overijssel"),
    "энсхеде": ("Enschede", "Overijssel"),
    "deventer": ("Deventer", "Overijssel"),
    "девентер": ("Deventer", "Overijssel"),
    # Flevoland
    "almere": ("Almere", "Flevoland"),
    "алмере": ("Almere", "Flevoland"),
    "lelystad": ("Lelystad", "Flevoland"),
    "лелистад": ("Lelystad", "Flevoland"),
    # Groningen
    "groningen": ("Groningen", "Groningen"),
    "гронинген": ("Groningen", "Groningen"),
    # Friesland
    "leeuwarden": ("Leeuwarden", "Friesland"),
    "леуварден": ("Leeuwarden", "Friesland"),
    # Drenthe
    "assen": ("Assen", "Drenthe"),
    "ассен": ("Assen", "Drenthe"),
    "emmen": ("Emmen", "Drenthe"),
    "эммен": ("Emmen", "Drenthe"),
    # Zeeland
    "middelburg": ("Middelburg", "Zeeland"),
    "мидделбург": ("Middelburg", "Zeeland"),
}

# Координаты центров нужны не для слежения за пользователем, а чтобы превратить
# абстрактное «25/50 км» в конкретный список городов для поиска мероприятий.
CITY_COORDS: dict[str, tuple[float, float]] = {
    "Amsterdam": (52.3676, 4.9041), "Haarlem": (52.3874, 4.6462),
    "Alkmaar": (52.6324, 4.7534), "Zaandam": (52.4385, 4.8264),
    "Hilversum": (52.2292, 5.1669), "Amstelveen": (52.3026, 4.8462),
    "Hoofddorp": (52.3061, 4.6907), "Rotterdam": (51.9244, 4.4777),
    "Den Haag": (52.0705, 4.3007), "Leiden": (52.1601, 4.4970),
    "Delft": (52.0116, 4.3571), "Dordrecht": (51.8133, 4.6901),
    "Zoetermeer": (52.0607, 4.4940), "Utrecht": (52.0907, 5.1214),
    "Amersfoort": (52.1561, 5.3878), "Eindhoven": (51.4416, 5.4697),
    "Tilburg": (51.5555, 5.0913), "Breda": (51.5719, 4.7683),
    "Den Bosch": (51.6978, 5.3037), "Helmond": (51.4793, 5.6570),
    "Oss": (51.7650, 5.5180), "Uden": (51.6608, 5.6194),
    "Veghel": (51.6167, 5.5486), "Wijchen": (51.8090, 5.7250),
    "Maastricht": (50.8514, 5.6910), "Venlo": (51.3704, 6.1724),
    "Heerlen": (50.8882, 5.9795), "Arnhem": (51.9851, 5.8987),
    "Nijmegen": (51.8426, 5.8528), "Apeldoorn": (52.2112, 5.9699),
    "Ede": (52.0402, 5.6649), "Zwolle": (52.5168, 6.0830),
    "Enschede": (52.2215, 6.8937), "Deventer": (52.2661, 6.1552),
    "Almere": (52.3508, 5.2647), "Lelystad": (52.5185, 5.4714),
    "Groningen": (53.2194, 6.5665), "Leeuwarden": (53.2012, 5.7999),
    "Assen": (52.9928, 6.5642), "Emmen": (52.7858, 6.8976),
    "Middelburg": (51.4988, 3.6109),
}


def distance_km(city_a: str, city_b: str) -> float | None:
    """Примерное расстояние между центрами городов по прямой."""
    a, b = CITY_COORDS.get(city_a), CITY_COORDS.get(city_b)
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def cities_within_radius(city: str, radius_km: int, *, limit: int = 8) -> list[str]:
    """Город пользователя + ближайшие известные города внутри его радиуса."""
    if radius_km == 999:
        return [city]
    if radius_km <= 0 or city not in CITY_COORDS:
        return [city]
    nearby = []
    for candidate in CITY_COORDS:
        distance = distance_km(city, candidate)
        if distance is not None and distance <= radius_km:
            nearby.append((distance, candidate))
    return [name for _, name in sorted(nearby)[:limit]] or [city]

# --- Категории специалистов и слова для распознавания ------------------------
# Ключ — каноничная категория (так же она хранится у специалиста в базе).
# Значение — список слов/корней, по которым ловим категорию в тексте запроса.
#
# ВАЖНО: порядок имеет значение — detect_category возвращает первую подходящую
# категорию, поэтому более узкие категории идут раньше общих ("услуги" — в конце).
# Набор категорий покрывает реальные профессии из гайда на сайте.
# ВАЖНО: порядок = приоритет. Узкие и однозначные категории идут РАНЬШЕ широких
# («репетитор», «творчество», «услуги» — в самом конце), иначе они «крадут» чужих.
CATEGORIES: dict[str, list[str]] = {
    # --- 💅 Красота и уход (узкие — раньше широких) ---
    "брови и ресницы": ["бровист", "брови", "ресниц", "ламинирован ресн", "ламинирован бров",
                          "наращиван ресн", "архитектур бров", "lash", "brow"],
    "перманентный макияж": ["перманент", "татуаж", "пудров бров", "микроблейдинг",
                             "permanent make"],
    "визажист": ["визаж", "макияж", "make-up", "makeup", "make up"],
    "мастер маникюра": ["маникюр", "педикюр", "ногт", "nail", "нейл"],
    "парикмахер": ["парикмахер", "колорист", "кератин", "стрижк", "барбер", "kapper",
                    "по волос", "окрашиван волос", "наращиван волос"],
    "эпиляция": ["эпиляц", "шугаринг", "депиляц", "восков"],
    "косметолог": ["косметолог", "уход за кож", "чистка лиц", "пилинг", "аппаратн косметол",
                    "эстетист", "бьюти", "beauty"],
    "массаж": ["массаж", "massage"],
    "тату и пирсинг": ["тату", "tattoo", "пирсинг", "piercing"],
    "стилист": ["стилист", "имидж", "имиджмейкер", "шопинг-сопров", "разбор гардероб"],
    # --- 🩺 Здоровье и тело ---
    "стоматолог": ["стоматолог", "дантист", "зубн", "dentist", "tandarts"],
    "нутрициолог": ["нутрициолог", "диетолог", "нутри", "аюрвед", "правильн питани", "по питанию"],
    "психолог": ["психолог", "психотерап", "психосоциальн", "арт-терап", "арттерап",
                  "расстановк", "гештальт", "psycholoog"],
    "коуч": ["коуч", "coach", "трансформацио", "духовн настав", "ментор", "лайф-коуч",
              "наставник по"],
    "врач": ["врач", "доктор", "терапевт", "педиатр", "остеопат", "физиотерап",
              "медицин", "huisarts", "поликлин"],
    "фитнес": ["фитнес", "персональн тренер", "йога", "пилатес", "танц", "dance", "трениров"],
    # --- ⚖️ Профессиональные услуги ---
    "юрист": ["юрист", "адвокат", "нотариус", "иммиграц", "юридическ", "advocaat", "lawyer"],
    "бухгалтер": ["бухгалтер", "налогов", "accountant", "belasting", "administratie",
                   "zzp", "финансов консультант", "финансовый консультант"],
    "переводчик": ["переводчик", "перевод докум", "перевод документ", "присяжн перевод",
                    "нотариальн перевод", "tolk", "vertaler"],
    "риелтор": ["маклер", "makelaar", "недвижим", "ипотек", "аренд жил", "риелтор", "риэлтор"],
    "it и веб": ["веб-разработ", "сайт под ключ", "вебсайт", "веб-сайт", "программист",
                  "разработчик", "айти", "it-специалист", "верстк", "приложен"],
    "маркетинг": ["маркетинг", "smm", "таргетолог", "реклам", "продвижен", "контент-менедж",
                   "сммщик", "маркетолог"],
    "дизайнер": ["дизайнер", "график дизайн", "логотип", "брендинг", "декоратор",
                  "интерьер", "ландшафт", "рестайлинг"],
    "бизнес-консалтинг": ["консалтинг", "сопровожд бизнес", "бизнес-консультант",
                           "открыт компани", "регистрац фирм", "kvk", "expat"],
    "карьерный консультант": ["резюме", "linkedin", "career", "карьер", "собеседован", "cv ", "по cv"],
    # --- 🎉 Праздники и контент ---
    "фотограф": ["фотограф", "фотосесс", "фотосъ", "съёмк", "съемк", "photo"],
    "видеограф": ["видеограф", "видеосъ", "видеомонтаж", "видеоопер", "videograf", "оператор"],
    "ведущий": ["ведущ", "тамада", "конферансье"],
    "музыкант": ["музыкант", "вокал", "пение", "поют", "оперн", "фортепиано", "пианино",
                  "гитар", "скрипк", "сольфеджио", "музыкальн", "диджей", " dj", "dj ", "кавер"],
    "декор": ["оформлен праздник", "оформлен зал", "воздушн шар", "шары на", "фотозон",
               "флорист", "цветочн оформлен", "арка из шар"],
    "аниматор": ["аниматор", "ростов", "аквагрим", "детский праздник"],
    "кондитер": ["кондитер", "торт", "десерт", "выпечк", "пирожн", "шоколад", "сладост",
                  "cake", "капкейк", "бенто"],
    "кейтеринг": ["кейтеринг", "catering", "повар", "кулинар", "ресторан", "доставка еды",
                   "пельмен", "икорн", "домашн обед"],
    # --- 🏠 Дом и быт ---
    "ремонт": ["ремонт квартир", "ремонт дом", "ремонт ванн", "строительн", "плотник",
                "отделочн", "отделк", "малярн", "плитк", "bouw", "verbouw"],
    "мастер на час": ["электрик", "сантехник", "газов", "котл", "klusjes", "handyman",
                       "тёплый пол", "теплый пол", "отоплен", "сборка мебел", "мастер на час"],
    "клининг": ["уборк", "клининг", "cleaning", "мойка окон", "химчистк"],
    "переезды": ["переезд", "грузоперевоз", "грузчик", "перевозк вещ", "verhuis",
                  "доставка мебел", "газель"],
    "автосервис": ["автосервис", "шиномонтаж", "ремонт авто", "garage", "автомеханик",
                    "автоэлектрик"],
    "автошкола": ["автошкол", "инструктор по вожден", "уроки вожден", "driving", "права категори"],
    # --- 👶 Дети и образование ---
    "языковые курсы": ["английск", "нидерландск", "голландск", "немецк", "испанск",
                        "французск", "inburger", "intoeg", "speakup", "language",
                        "преподавател язык", "курс язык", "разговорн язык", "носител язык",
                        "школа язык", "языков"],
    "репетитор": ["репетитор", "школьн предмет", "математик", "tutor", "подготовк к экзам",
                   "химия репет", "физик репет"],
    "няня": ["няня", "babysit", "бэбиситт", "бебиситт", "сиделка", "уходу за реб",
              "посидеть с реб", "гувернантк"],
    "детские занятия": ["детск студи", "развивашк", "логопед", "раннее развит",
                         "детский клуб", "кружок для дет", "детск занятия"],
    # --- 🧭 Прочее ---
    "гид": ["экскурс", "гид по", "гид в", "тур по", "прогулк по город", "о голландии", "guide"],
    "творчество": ["керамик", "рисован", "живопис", "лепк", "рукодел", "арт-студи",
                    "арт-посидел", "мастер-класс", "театр", "вышив", "скрапбук", "хор "],
}
# Темы для 2-уровневого просмотра (тема → список категорий). Каждая категория —
# ровно в одной теме. Используется при просмотре по кнопкам.
THEMES: dict[str, list[str]] = {
    "💅 Красота и уход": ["парикмахер", "мастер маникюра", "брови и ресницы",
                          "перманентный макияж", "визажист", "косметолог", "эпиляция",
                          "массаж", "тату и пирсинг", "стилист"],
    "🩺 Здоровье и тело": ["стоматолог", "врач", "психолог", "коуч", "нутрициолог", "фитнес"],
    "⚖️ Профуслуги": ["юрист", "бухгалтер", "переводчик", "риелтор", "it и веб",
                      "маркетинг", "дизайнер", "бизнес-консалтинг", "карьерный консультант"],
    "🎉 Праздники и контент": ["фотограф", "видеограф", "ведущий", "музыкант", "декор",
                              "аниматор", "кондитер", "кейтеринг"],
    "🏠 Дом и быт": ["ремонт", "мастер на час", "клининг", "переезды", "автосервис", "автошкола"],
    "👶 Дети и образование": ["репетитор", "языковые курсы", "няня", "детские занятия"],
    "🧭 Прочее": ["гид", "творчество"],
}
# Технические пустые ключи убираем (оставлены для читаемости порядка — фильтруем)
CATEGORIES = {k: v for k, v in CATEGORIES.items() if v}


def province_of_city(city: str) -> str | None:
    """По названию города возвращает провинцию (или None, если город неизвестен)."""
    found = CITY_TO_PROVINCE.get(city.strip().lower())
    return found[1] if found else None


def detect_city(text: str) -> tuple[str, str] | None:
    """Ищет в тексте название города. Возвращает (город, провинция) или None.

    Поиск по вхождению, поэтому ловит и склонённые формы:
    "в Амстердаме" содержит "амстердам", "из Роттердама" — "роттердам".
    Сначала проверяем самые длинные названия (чтобы "den haag" сработало
    раньше, чем отдельные короткие слова).
    """
    low = text.lower()
    for key in sorted(CITY_TO_PROVINCE, key=len, reverse=True):
        if key in low:
            return CITY_TO_PROVINCE[key]
    return None


def detect_category(text: str) -> str | None:
    """Определяет категорию специалиста по тексту запроса (или None)."""
    low = text.lower()
    for category, keywords in CATEGORIES.items():
        for kw in keywords:
            if kw in low:
                return category
    return None
