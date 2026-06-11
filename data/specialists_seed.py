"""ПРИМЕРЫ специалистов для проверки работы бота.

ВНИМАНИЕ: это тестовые данные-заглушки. Их нужно заменить реальными
контактами из гайда на сайте. Категория должна совпадать с ключами
из CATEGORIES в utils/geo.py, город — из CITY_TO_PROVINCE.
"""

SEED_SPECIALISTS: list[dict] = [
    {
        "name": "Иван Зубов (пример)",
        "category": "стоматолог",
        "city": "Amsterdam",
        "description": "Стоматолог, русскоязычный приём",
        "contact": "@example_dentist",
    },
    {
        "name": "Tandarts Centrum (пример)",
        "category": "стоматолог",
        "city": "Haarlem",
        "description": "Семейная стоматология",
        "contact": "+31 00 000 0000",
    },
    {
        "name": "Мария Право (пример)",
        "category": "юрист",
        "city": "Rotterdam",
        "description": "Иммиграционное право, помощь с документами",
        "contact": "@example_lawyer",
    },
    {
        "name": "Beauty Studio (пример)",
        "category": "косметолог",
        "city": "Utrecht",
        "description": "Маникюр, брови, ресницы",
        "contact": "https://example.com",
    },
    {
        "name": "Анна Фото (пример)",
        "category": "фотограф",
        "city": "Eindhoven",
        "description": "Семейные и контентные фотосессии",
        "contact": "@example_photo",
    },
]
