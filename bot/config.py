from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class BotConfig:
    """Передаёт runtime-настройки бота: токен Telegram и базовый URL сайта для login-ссылок."""

    token: str
    site_base_url: str


def get_bot_config() -> BotConfig:
    """Возвращает конфигурацию бота из Django settings и валидирует обязательный Telegram token."""
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в окружении.")
    return BotConfig(token=settings.TELEGRAM_BOT_TOKEN, site_base_url=settings.SITE_BASE_URL)
