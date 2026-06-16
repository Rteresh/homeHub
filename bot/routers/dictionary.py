from aiogram import F, Bot, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async

from apps.accounts.models import TelegramProfile
from bot.services.dictionary import (
    DictionaryBatch,
    get_next_dictionary_batch,
    get_previous_dictionary_batch,
)

router = Router()

MAX_DICTIONARY_MESSAGE_LENGTH = 3900


@router.message(Command("dictionary", "dict"))
@router.message(F.text.casefold() == "словарь")
async def dictionary_command(message: Message, telegram_profile: TelegramProfile) -> None:
    """Отправляет пользователю следующие 10 словарных статей и сохраняет позицию для продолжения."""
    batch = await sync_to_async(get_next_dictionary_batch)(telegram_profile)
    await send_dictionary_batch(message, batch)


@router.callback_query(F.data == "dictionary:next")
async def dictionary_next(callback: CallbackQuery, telegram_profile: TelegramProfile) -> None:
    """Обрабатывает inline-кнопку «Ещё»: берёт следующие 10 статей от сохранённой позиции профиля."""
    batch = await sync_to_async(get_next_dictionary_batch)(telegram_profile)
    await send_dictionary_batch(callback.message, batch)
    await callback.answer()


@router.callback_query(F.data == "dictionary:previous")
async def dictionary_previous(callback: CallbackQuery, telegram_profile: TelegramProfile) -> None:
    """Обрабатывает inline-кнопку «Назад»: возвращает предыдущие 10 статей и обновляет позицию профиля."""
    batch = await sync_to_async(get_previous_dictionary_batch)(telegram_profile)
    await send_dictionary_batch(callback.message, batch)
    await callback.answer()


async def send_next_dictionary_batch_to_chat(bot: Bot, profile: TelegramProfile) -> None:
    """Отправляет утреннюю порцию словаря в сохранённый chat_id профиля, если пользователь уже писал боту."""
    if profile.chat_id is None:
        return

    batch = await sync_to_async(get_next_dictionary_batch)(profile)
    chunks = format_dictionary_chunks(batch)
    for index, chunk in enumerate(chunks):
        reply_markup = dictionary_keyboard() if index == len(chunks) - 1 else None
        await bot.send_message(profile.chat_id, chunk, reply_markup=reply_markup)


async def send_dictionary_batch(message: Message | None, batch: DictionaryBatch) -> None:
    """Отправляет выбранный блок словаря в Telegram-сообщение и добавляет навигационные inline-кнопки."""
    if message is None:
        return

    chunks = format_dictionary_chunks(batch)
    for index, chunk in enumerate(chunks):
        reply_markup = dictionary_keyboard() if index == len(chunks) - 1 else None
        await message.answer(chunk, reply_markup=reply_markup)


def format_dictionary_chunks(batch: DictionaryBatch) -> list[str]:
    """Формирует текстовые части Telegram-сообщения так, чтобы длинные толкования не превышали лимит длины."""
    if not batch.entries:
        return ["Словарь пока пуст."]

    header = f"Толковый словарь: {batch.start_position + 1}-{batch.start_position + len(batch.entries)} из {batch.total_count}"
    chunks: list[str] = []
    current = header
    for entry in batch.entries:
        entry_text = f"{entry.position + 1}. {entry.title}\n{entry.sense}"
        if len(current) + len(entry_text) + 2 > MAX_DICTIONARY_MESSAGE_LENGTH:
            chunks.extend(split_long_text(current))
            current = entry_text
        else:
            current = f"{current}\n\n{entry_text}"
    chunks.extend(split_long_text(current))
    return chunks


def split_long_text(text: str) -> list[str]:
    """Разбивает один длинный текст на допустимые для Telegram куски без изменения словарных данных."""
    return [
        text[start : start + MAX_DICTIONARY_MESSAGE_LENGTH]
        for start in range(0, len(text), MAX_DICTIONARY_MESSAGE_LENGTH)
    ]


def dictionary_keyboard() -> InlineKeyboardMarkup:
    """Создаёт inline-навигацию словаря: следующая и предыдущая порции по 10 статей."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Назад", callback_data="dictionary:previous"),
                InlineKeyboardButton(text="Ещё", callback_data="dictionary:next"),
            ]
        ]
    )
