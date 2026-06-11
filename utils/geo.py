"""География Нидерландов и категории специалистов для умного поиска.

Здесь:
- какие города к какой провинции относятся (CITY_TO_PROVINCE);
- какие провинции соседствуют (NEIGHBORS) — чтобы предлагать специалистов
  из соседних регионов, если в нужном городе никого нет;
- категории специалистов и слова-синонимы для распознавания запроса (CATEGORIES).

Города пишем и по-русски, и по-английски/нидерландски (как люди реально пишут).
"""

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

# --- Категории специалистов и слова для распознавания ------------------------
# Ключ — каноничная категория (так же она хранится у специалиста в базе).
# Значение — список слов/корней, по которым ловим категорию в тексте запроса.
#
# ВАЖНО: порядок имеет значение — detect_category возвращает первую подходящую
# категорию, поэтому более узкие категории идут раньше общих ("услуги" — в конце).
# Набор категорий покрывает реальные профессии из гайда на сайте.
CATEGORIES: dict[str, list[str]] = {
    "стоматолог": ["стоматолог", "дантист", "зуб", "dentist", "tandarts"],
    "нутрициолог": ["нутрициолог", "диетолог", "аюрвед", "нутри", "правильн питани"],
    "психолог": ["психолог", "психотерап", "психосоциальн", "арт-терап", "арттерап",
                  "кинотерап", "актерская терап", "актёрская терап", "коуч", "расстановк",
                  "духовны", "трансформацио", "психологическ", "psycholoog"],
    "врач": ["врач", "доктор", "терапевт", "физиотерап", "двигательн", "медицин",
              "остеопат", "педиатр", "поликлиник", "huisarts", "gp"],
    "юрист": ["юрист", "адвокат", "нотариус", "иммиграц", "юридическ", "advocaat", "lawyer"],
    "бухгалтер": ["бухгалтер", "налог", "accountant", "belasting", "финансов",
                   "administratie", "zzp", "tax"],
    "риелтор": ["маклер", "makelaar", "недвижим", "аренд", "ипотек", "жиль", "риелтор", "риэлтор"],
    "репетитор": ["репетитор", "преподавател", "учител", "школ", "курс", "обучен", "урок",
                   "язык", "английск", "нидерландск", "голландск", "вокал", "вокала", "музык",
                   "логопед", "tutor", "speakup", "интеграц"],
    "парикмахер": ["парикмахер", "колорист", "кератин", "стрижк", "hair", "kapper", "барбер", "волос"],
    "мастер маникюра": ["маникюр", "педикюр", "ногт", "nail", "nailart", "нейл"],
    "косметолог": ["косметолог", "бровист", "ламин", "ресниц", "перманент", "макияж",
                    "эпиляц", "beauty", "brow", "lash", "pmu", "уход за кож", "бьюти"],
    "массаж": ["массаж", "massage"],
    "тату": ["тату", "tattoo", "перманентн рисун"],
    "фотограф": ["фотограф", "photo", "съемк", "съёмк", "фотосесс"],
    "дизайнер": ["дизайнер", "декоратор", "рестайлинг", "интерьер"],
    "ремонт": ["ремонт", "строит", "плотник", "отделк", "текстурн", "бригад", "remont", "bouw"],
    "мастер на час": ["электрик", "сантехник", "газов", "котл", "klusjesman", "handyman",
                       "тёплый пол", "теплый пол", "отоплен"],
    "клининг": ["уборк", "клининг", "cleaning", "мойка окон", "clean"],
    "кондитер": ["кондитер", "торт", "десерт", "выпечк", "сладост", "шоколад",
                  "клубник", "пирожн", "cake", "mariday"],
    "еда": ["кейтеринг", "повар", "кулинар", "икорн", "ресторан", "catering"],
    "няня": ["няня", "babysit", "бэбиситт", "сиделк"],
    "аниматор": ["аниматор"],
    "фитнес": ["тренер", "фитнес", "пилатес", "йога", "спорт", "танц", "dance", "fitness"],
    "гид": ["гид", "экскурс", "тур ", "туры", "тура"],
    "ведущий": ["event", "диджей", " dj", "dj ", "ведущ", "праздник", "мероприят"],
    "стилист": ["стилист", "имидж", "шопинг"],
    "автошкола": ["автошкол", "инструктор по вожден", "driving"],
    "веб-разработчик": ["веб-разработ", "web", "сайт", "digital", "программист", "разработчик"],
    "творчество": ["керамик", "art studio", "арт-студи", "рисован", "живопис", "арт-посиделк",
                    "art code", "хор", "театр", "art "],
    "автосервис": ["автосервис", "шиномонтаж", "garage"],
    # запасная категория — если ничего конкретного не подошло
    "услуги": ["услуг", "сервис", "консультац", "expat", "консалтинг"],
}


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
