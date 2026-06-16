from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class BotConfig:
    """Передаёт runtime-настройки бота: токен, URL сайта, таймаут скачивания и опции Local Bot API."""

    token: str
    site_base_url: str
    download_timeout: int
    api_base_url: str
    local_mode: bool
    local_files_path: str


def get_bot_config() -> BotConfig:
    """Возвращает конфигурацию бота из Django settings и валидирует обязательный Telegram token."""
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в окружении.")
    return BotConfig(
        token=settings.TELEGRAM_BOT_TOKEN,
        site_base_url=settings.SITE_BASE_URL,
        download_timeout=settings.TELEGRAM_DOWNLOAD_TIMEOUT,
        api_base_url=settings.TELEGRAM_API_BASE_URL,
        local_mode=settings.TELEGRAM_LOCAL_MODE,
        local_files_path=settings.TELEGRAM_LOCAL_FILES_PATH,
    )
