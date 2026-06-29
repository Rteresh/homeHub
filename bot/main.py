import asyncio
import contextlib
import logging
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "homehub.settings")

import django

django.setup()

from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import SimpleFilesPathWrapper, TelegramAPIServer
from aiogram.exceptions import TelegramAPIError
from asgiref.sync import sync_to_async

from apps.accounts.models import TelegramProfile
from bot.config import get_bot_config
from bot.middlewares.auth import TelegramAuthMiddleware
from bot.routers import admin, album, dictionary, media

logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
DICTIONARY_SEND_TIME = time(hour=9, minute=0)


def configure_logging() -> None:
    """Пишет логи бота в storage/logs/bot.log и в stderr (для docker compose logs)."""
    from django.conf import settings

    log_dir = Path(settings.HOMEHUB_STORAGE_ROOT) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "bot.log"

    root_logger = logging.getLogger()
    if any(isinstance(handler, logging.FileHandler) and handler.baseFilename == str(log_path) for handler in root_logger.handlers):
        return

    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)


def create_bot(config) -> Bot:
    """Создаёт aiogram Bot с production API или с Local Bot API server при наличии настроек."""
    if not config.api_base_url:
        return Bot(token=config.token)

    if config.local_mode and not config.local_files_path:
        raise RuntimeError(
            "TELEGRAM_LOCAL_MODE=true требует TELEGRAM_LOCAL_FILES_PATH с путём к --dir Local Bot API."
        )

    wrap_local_file = SimpleFilesPathWrapper(
        server_path=Path(config.local_files_path) if config.local_files_path else Path("/"),
        local_path=Path(config.local_files_path) if config.local_files_path else Path("/"),
    )
    api = TelegramAPIServer.from_base(
        config.api_base_url,
        is_local=config.local_mode,
        wrap_local_file=wrap_local_file,
    )
    session = AiohttpSession(api=api)
    return Bot(token=config.token, session=session)


async def main() -> None:
    """Запускает long polling Telegram-бота и подключает middleware авторизации и роутеры приёма данных."""
    configure_logging()
    config = get_bot_config()
    bot = create_bot(config)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.message.middleware(TelegramAuthMiddleware())
    dispatcher.callback_query.middleware(TelegramAuthMiddleware())
    dispatcher.include_router(admin.router)
    dispatcher.include_router(album.router)
    dispatcher.include_router(media.router)
    dispatcher.include_router(dictionary.router)
    scheduler_task = asyncio.create_task(dictionary_morning_scheduler(bot))
    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task


async def dictionary_morning_scheduler(bot: Bot) -> None:
    """Каждый день ждёт 09:00 по Москве и отправляет всем активным Telegram-профилям следующую порцию словаря."""
    while True:
        await asyncio.sleep(seconds_until_next_moscow_morning())
        await send_morning_dictionary_batches(bot)


def seconds_until_next_moscow_morning() -> float:
    """Считает задержку до ближайших 09:00 МСК, чтобы фоновая задача не зависела от timezone сервера."""
    now = datetime.now(MOSCOW_TZ)
    target = datetime.combine(now.date(), DICTIONARY_SEND_TIME, tzinfo=MOSCOW_TZ)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def send_morning_dictionary_batches(bot: Bot) -> None:
    """Выбирает разрешённые профили с chat_id и отправляет каждому его следующие 10 словарных статей."""
    profiles_queryset = (
        TelegramProfile.objects.filter(is_allowed=True, chat_id__isnull=False)
        .select_related("user")
        .order_by("id")
    )
    profiles = await sync_to_async(list)(profiles_queryset)
    for profile in profiles:
        try:
            await dictionary.send_next_dictionary_batch_to_chat(bot, profile)
        except TelegramAPIError:
            logger.exception("Не удалось отправить словарь в Telegram chat_id=%s", profile.chat_id)


if __name__ == "__main__":
    asyncio.run(main())
