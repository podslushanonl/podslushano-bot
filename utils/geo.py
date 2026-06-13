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
# ВАЖНО: порядок = приоритет. Узкие и однозначные категории идут РАНЬШЕ широких
# («репетитор», «творчество», «услуги» — в самом конце), иначе они «крадут» чужих.
CATEGORIES: dict[str, list[str]] = {
    "ведущий": ["диджей", " dj", "dj ", "ведущ", "тамада", "конферансье"],
    "нутрициолог": ["нутрициолог", "диетолог", "нутри", "аюрвед", "правильн питани"],
    "психолог": ["психолог", "психотерап", "психосоциальн", "арт-терап", "арттерап",
                  "расстановк", "трансформацио", "духовн", "коуч", "гештальт", "psycholoog"],
    "музыка": ["вокал", "пение", "поют", "оперн", "фортепиано", "пианино", "гитар",
                "скрипк", "сольфеджио", "музыкальн", "уроки музык"],
    "стоматолог": ["стоматолог", "дантист", "зубн", "dentist", "tandarts"],
    "врач": ["врач", "доктор", "терапевт", "педиатр", "остеопат", "физиотерап",
              "медицин", "huisarts", "поликлин"],
    "юрист": ["юрист", "адвокат", "нотариус", "иммиграц", "юридическ", "advocaat", "lawyer"],
    "бухгалтер": ["бухгалтер", "налог", "accountant", "belasting", "administratie", "zzp", "финансов"],
    "риелтор": ["маклер", "makelaar", "недвижим", "ипотек", "аренд жил", "риелтор", "риэлтор"],
    "фотограф": ["фотограф", "фотосесс", "фотосъ", "съёмк", "съемк", "photo"],
    "парикмахер": ["парикмахер", "колорист", "кератин", "стрижк", "барбер", "kapper", "по волос"],
    "косметолог": ["косметолог", "бровист", "ламинир", "ресниц", "перманентн макияж",
                    "макияж", "визаж", "эпиляц", "brow", "lash", "уход за кож", "бьюти", "beauty"],
    "мастер маникюра": ["маникюр", "педикюр", "ногт", "nail", "нейл"],
    "массаж": ["массаж", "massage"],
    "тату": ["тату", "tattoo"],
    "кондитер": ["кондитер", "торт", "десерт", "выпечк", "пирожн", "шоколад", "сладост", "cake", "капкейк"],
    "еда": ["кейтеринг", "catering", "повар", "кулинар", "ресторан", "доставка еды", "пельмен", "икорн"],
    "няня": ["няня", "babysit", "бэбиситт", "бебиситт", "сиделка", "уходу за реб", "посидеть с реб"],
    "аниматор": ["аниматор", "ростов", "аквагрим", "детский праздник"],
    "автошкола": ["автошкол", "инструктор по вожден", "уроки вожден", "driving"],
    "гид": ["экскурс", "гид по", "гид в", "тур по", "прогулк по город", "о голландии", "guide"],
    "дизайнер": ["дизайнер", "декоратор", "интерьер", "рестайлинг", "ландшафт"],
    "фитнес": ["фитнес", "персональн тренер", "йога", "пилатес", "танц", "dance", "трениров"],
    "стилист": ["стилист", "имидж", "шопинг-сопров", "разбор гардероб"],
    "веб-разработчик": ["веб-разработ", "веб-сайт", "сайт под ключ", "программист",
                         "разработчик", "вебсайт", "smm", "таргетолог"],
    "автосервис": ["автосервис", "шиномонтаж", "ремонт авто", "garage"],
    "ремонт": ["ремонт квартир", "ремонт дом", "ремонт ванн", "строительн", "плотник",
                "отделочн", "отделк", "малярн", "плитк", "bouw"],
    "мастер на час": ["электрик", "сантехник", "газов", "котл", "klusjes", "handyman",
                       "тёплый пол", "теплый пол", "отоплен", "сборка мебел", "мастер на час"],
    "клининг": ["уборк", "клининг", "cleaning", "мойка окон", "химчистк"],
    "творчество": ["керамик", "рисован", "живопис", "лепк", "рукодел", "арт-студи",
                    "арт-посидел", "мастер-класс", "театр", "вышив", "скрапбук", "хор "],
    "репетитор": ["репетитор", "преподавател", "учител", "школьн предмет", "курс ", "обучен",
                   "урок", "язык", "английск", "нидерландск", "голландск", "немецк", "испанск",
                   "логопед", "интеграц", "tutor", "speakup", "inburger"],
    "услуги": ["резюме", "linkedin", "career", "карьер", "собеседован", "консультац",
                "консалтинг", "expat", "перевод докум", "сопровожд", "сервис", "услуг"],
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
