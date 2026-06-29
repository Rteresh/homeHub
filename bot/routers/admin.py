import asyncio

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from django.conf import settings

from apps.accounts.models import TelegramProfile
from bot.routers.album import SHUTDOWN_BUTTON
from bot.services.shutdown import schedule_server_shutdown

router = Router()

SHUTDOWN_CONFIRM_CALLBACK = "admin:shutdown:confirm"
SHUTDOWN_CANCEL_CALLBACK = "admin:shutdown:cancel"
SHUTDOWN_CONFIRM_TEXT = "Вы уверены, что хотите выключить сервер"


def shutdown_confirm_keyboard() -> InlineKeyboardMarkup:
    """Inline-кнопки подтверждения выключения сервера."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Выкл.", callback_data=SHUTDOWN_CONFIRM_CALLBACK),
                InlineKeyboardButton(text="Нет", callback_data=SHUTDOWN_CANCEL_CALLBACK),
            ]
        ]
    )


def ensure_bot_admin(telegram_profile: TelegramProfile) -> bool:
    """Проверяет, что Telegram-профиль помечен как администратор бота."""
    return bool(telegram_profile.is_bot_admin)


@router.message(F.text.casefold() == SHUTDOWN_BUTTON.casefold())
async def shutdown_prompt(message: Message, telegram_profile: TelegramProfile) -> None:
    """Показывает подтверждение выключения сервера — только для администратора бота."""
    if not ensure_bot_admin(telegram_profile):
        await message.answer("Эта команда доступна только администратору бота.")
        return

    if not (settings.HOMEHUB_SHUTDOWN_COMMAND or "").strip():
        await message.answer("Выключение сервера не настроено (HOMEHUB_SHUTDOWN_COMMAND).")
        return

    await message.answer(SHUTDOWN_CONFIRM_TEXT, reply_markup=shutdown_confirm_keyboard())


@router.callback_query(F.data == SHUTDOWN_CANCEL_CALLBACK)
async def shutdown_cancel(callback: CallbackQuery, telegram_profile: TelegramProfile) -> None:
    """Отменяет выключение сервера по inline-кнопке «Нет»."""
    if not ensure_bot_admin(telegram_profile):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    await callback.answer("Отменено")
    if callback.message:
        await callback.message.edit_text("Выключение сервера отменено.")


@router.callback_query(F.data == SHUTDOWN_CONFIRM_CALLBACK)
async def shutdown_confirm(callback: CallbackQuery, telegram_profile: TelegramProfile) -> None:
    """Выключает сервер после подтверждения администратором бота."""
    if not ensure_bot_admin(telegram_profile):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    if not (settings.HOMEHUB_SHUTDOWN_COMMAND or "").strip():
        await callback.answer("Выключение не настроено.", show_alert=True)
        return

    await callback.answer("Сервер выключается")
    if callback.message:
        await callback.message.edit_text("Сервер выключается…")
    asyncio.create_task(schedule_server_shutdown())
