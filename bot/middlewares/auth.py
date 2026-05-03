from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message
from asgiref.sync import sync_to_async

from apps.accounts.services import TelegramIdentityService


class TelegramAuthMiddleware(BaseMiddleware):
    """Проверяет Telegram user_id в БД и передаёт Django-пользователя в handler как `django_user`."""

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if not event.from_user:
            await event.answer("Не удалось определить пользователя Telegram.")
            return None

        user = await sync_to_async(TelegramIdentityService.find_allowed_user)(event.from_user.id)
        if not user:
            await event.answer("Доступ закрыт. Ваш Telegram ID не добавлен в HomeHub.")
            return None

        profile = user.telegram_profile
        update_fields = []
        profile_updates = {
            "chat_id": event.chat.id,
            "telegram_username": event.from_user.username or "",
            "first_name": event.from_user.first_name or "",
            "last_name": event.from_user.last_name or "",
        }
        for field_name, value in profile_updates.items():
            if getattr(profile, field_name) != value:
                setattr(profile, field_name, value)
                update_fields.append(field_name)
        if update_fields:
            update_fields.append("updated_at")
            await sync_to_async(profile.save)(update_fields=update_fields)

        data["django_user"] = user
        data["telegram_profile"] = profile
        return await handler(event, data)
