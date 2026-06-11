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
    # Overijssel
    "zwolle": ("Zwolle", "Overijssel"),
    "зволле": ("Zwolle", "Overijssel"),
    "enschede": ("Enschede", "Overijssel"),
    "энсхеде": ("Enschede", "Overijssel"),
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
    # Zeeland
    "middelburg": ("Middelburg", "Zeeland"),
    "мидделбург": ("Middelburg", "Zeeland"),
}

# --- Категории специалистов и слова для распознавания ------------------------
# Ключ — каноничная категория (так же она хранится у специалиста в базе).
# Значение — список слов/корней, по которым ловим категорию в тексте запроса.
CATEGORIES: dict[str, list[str]] = {
    "стоматолог": ["стоматолог", "дантист", "зуб", "dentist", "tandarts"],
    "врач": ["врач", "терапевт", "доктор", "поликлиник", "huisarts", "gp"],
    "юрист": ["юрист", "адвокат", "юридическ", "lawyer", "advocaat"],
    "парикмахер": ["парикмахер", "барбер", "стрижк", "kapper", "barber", "hairdresser"],
    "косметолог": ["косметолог", "бровист", "ноготь", "ногти", "маникюр", "ресниц", "nails", "beauty"],
    "фотограф": ["фотограф", "фотосесс", "photographer", "photo"],
    "репетитор": ["репетитор", "учитель", "преподавател", "tutor", "урок"],
    "бухгалтер": ["бухгалтер", "налог", "accountant", "belasting", "tax"],
    "психолог": ["психолог", "психотерапевт", "psycholoog"],
    "мастер на час": ["ремонт", "мастер", "сантехник", "электрик", "klusjesman", "handyman"],
    "риелтор": ["риелтор", "риэлтор", "недвижимост", "аренд", "makelaar", "жиль"],
    "автосервис": ["автосервис", "машин", "шиномонтаж", "garage", "авто"],
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
