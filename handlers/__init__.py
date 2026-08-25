# Подключаем патч месячной афиши при загрузке пакета handlers.
# Модуль не вызывает AI: он только находит официальный сайт/фото HTTP-запросами.
from handlers import photo_refresh as _photo_refresh  # noqa: F401,E402

# Контент-центр: два action-поста в неделю вместо старых коротких напоминаний.
# Импорт content здесь намеренный: бот затем получает уже настроенный модуль.
from handlers import content as _content  # noqa: F401,E402
from utils.action_content import install_action_templates as _install_action_templates  # noqa: E402

_install_action_templates()

# Редакционная система раньше устанавливалась в неверном порядке: caption/media patch
# применялся при импорте handlers, а затем bot.main вызывал editorial_overrides.install()
# и перезаписывал часть правил. Оборачиваем install один раз, чтобы итоговый runtime
# всегда был: base overrides -> caption/media rules -> scheduler reliability.
from utils import editorial_caption_patch as _editorial_caption_patch  # noqa: F401,E402
from utils import editorial_overrides as _editorial_overrides  # noqa: E402
from utils.editorial_reliability import install_editorial_reliability as _install_editorial_reliability  # noqa: E402

_original_editorial_install = _editorial_overrides.install


def _install_editorial_stack() -> None:
    _original_editorial_install()
    _editorial_caption_patch.install_caption_patch()
    _install_editorial_reliability()


_editorial_overrides.install = _install_editorial_stack
