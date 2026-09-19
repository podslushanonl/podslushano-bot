"""Shared utility package initialization."""

# Keep the canonical /ads product definitions available even when utilities or
# the webserver are imported outside bot.py (for example in tests or scripts).
import ad_products_runtime  # noqa: F401
