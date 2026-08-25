# Подключаем патч месячной афиши при загрузке пакета handlers.
# Модуль не вызывает AI: он только находит официальный сайт/фото HTTP-запросами.
from handlers import photo_refresh as _photo_refresh  # noqa: F401,E402

# Контент-центр: два action-поста в неделю вместо старых коротких напоминаний.
# Импорт content здесь намеренный: бот затем получает уже настроенный модуль.
from handlers import content as _content  # noqa: F401,E402
from utils.action_content import install_action_templates as _install_action_templates  # noqa: E402

_install_action_templates()
