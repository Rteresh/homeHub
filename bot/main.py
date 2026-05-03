import asyncio
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "homehub.settings")

import django

django.setup()

from aiogram import Bot, Dispatcher

from bot.config import get_bot_config
from bot.middlewares.auth import TelegramAuthMiddleware
from bot.routers import media


async def main() -> None:
    """Запускает long polling Telegram-бота и подключает middleware авторизации и роутеры приёма данных."""
    config = get_bot_config()
    bot = Bot(token=config.token)
    dispatcher = Dispatcher()
    dispatcher.message.middleware(TelegramAuthMiddleware())
    dispatcher.include_router(media.router)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
