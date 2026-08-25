# Подключаем патч месячной афиши при загрузке пакета handlers.
# Модуль не вызывает AI: он только находит официальный сайт/фото HTTP-запросами.
from handlers import photo_refresh as _photo_refresh  # noqa: F401,E402

# Контент-центр: два action-поста в неделю вместо старых коротких напоминаний.
# Импорт content здесь намеренный: бот затем получает уже настроенный модуль.
from handlers import content as _content  # noqa: F401,E402
from utils.action_content import install_action_templates as _install_action_templates  # noqa: E402

_install_action_templates()

# Редакционный runtime собираем строго в одном порядке.
from utils import editorial_caption_patch as _editorial_caption_patch  # noqa: F401,E402
from utils import editorial_overrides as _editorial_overrides  # noqa: E402
from utils.editorial_reliability import install_editorial_reliability as _install_editorial_reliability  # noqa: E402
from utils import editorial_websearch_fix as _editorial_websearch_fix  # noqa: F401,E402
from utils.editorial_cost_guard import install_editorial_cost_guard as _install_editorial_cost_guard  # noqa: E402

_original_editorial_install = _editorial_overrides.install


def _install_editorial_stack() -> None:
    # 1. Базовые overrides: фото, preview, CTA.
    _original_editorial_install()
    # 2. Telegram caption/media rules.
    _editorial_caption_patch.install_caption_patch()
    # 3. Надёжный scheduler: retry/catch-up/alerts.
    _install_editorial_reliability()
    # 4. Устойчивый вечерний генератор.
    _editorial_websearch_fix.install_editorial_websearch_fix()
    # 5. ПОСЛЕДНИМ — жёсткий cost guard: только Haiku, 1 web-search, без платного health probe.
    _install_editorial_cost_guard()


_editorial_overrides.install = _install_editorial_stack
