from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import Message
from django.conf import settings

logger = logging.getLogger(__name__)

TELEGRAM_BOT_DOWNLOAD_LIMIT_BYTES = 20 * 1024 * 1024


class TelegramFileTooLarge(Exception):
    """Сообщает, что файл превышает лимит стандартного Telegram Bot API без Local Bot API server."""


class TelegramDownloadFailed(Exception):
    """Сообщает о сбое скачивания файла из Telegram с понятным текстом для пользователя."""


@dataclass(frozen=True)
class MediaPayload:
    """Описывает файл из Telegram update: идентификатор, имя, MIME-тип и размер в байтах."""

    file_id: str
    original_name: str
    mime_type: str
    file_size: int | None


def extract_media_payload(message: Message) -> MediaPayload | None:
    """Достаёт file_id, имя, MIME и file_size из фото, видео, GIF, аудио, голосового или документа Telegram."""
    if message.photo:
        photo = message.photo[-1]
        return MediaPayload(
            file_id=photo.file_id,
            original_name=f"telegram_photo_{message.message_id}.jpg",
            mime_type="image/jpeg",
            file_size=photo.file_size,
        )
    if message.video:
        name = message.video.file_name or f"telegram_video_{message.message_id}.mp4"
        return MediaPayload(
            file_id=message.video.file_id,
            original_name=Path(name).name,
            mime_type=message.video.mime_type or "video/mp4",
            file_size=message.video.file_size,
        )
    if message.animation:
        name = message.animation.file_name or f"telegram_gif_{message.message_id}.gif"
        return MediaPayload(
            file_id=message.animation.file_id,
            original_name=Path(name).name,
            mime_type=message.animation.mime_type or "image/gif",
            file_size=message.animation.file_size,
        )
    if message.audio:
        name = message.audio.file_name or f"telegram_audio_{message.message_id}.mp3"
        return MediaPayload(
            file_id=message.audio.file_id,
            original_name=Path(name).name,
            mime_type=message.audio.mime_type or "audio/mpeg",
            file_size=message.audio.file_size,
        )
    if message.voice:
        return MediaPayload(
            file_id=message.voice.file_id,
            original_name=f"telegram_voice_{message.message_id}.ogg",
            mime_type=message.voice.mime_type or "audio/ogg",
            file_size=message.voice.file_size,
        )
    if message.document:
        name = message.document.file_name or f"telegram_file_{message.message_id}"
        return MediaPayload(
            file_id=message.document.file_id,
            original_name=Path(name).name,
            mime_type=message.document.mime_type or "",
            file_size=message.document.file_size,
        )
    return None


def is_file_too_large_for_standard_api(file_size: int | None) -> bool:
    """Возвращает True, если размер известен и превышает лимит 20 МБ стандартного Bot API."""
    if file_size is None:
        return False
    return file_size > TELEGRAM_BOT_DOWNLOAD_LIMIT_BYTES


def build_temp_download_path() -> Path:
    """Создаёт уникальный путь во временной директории storage/tmp для скачанного Telegram-файла."""
    tmp_dir = Path(settings.HOMEHUB_STORAGE_ROOT) / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir / f"telegram_{uuid4().hex}.bin"


async def download_telegram_file(bot: Bot, file_id: str, *, timeout: int) -> Path:
    """Скачивает Telegram-файл во временный путь на диске и поднимает понятные ошибки при отказе API."""
    destination = build_temp_download_path()
    try:
        await bot.download(file_id, destination=destination, timeout=timeout)
    except TelegramBadRequest as exc:
        cleanup_temp(destination)
        if "file is too big" in str(exc).lower():
            raise TelegramFileTooLarge(
                "Файл слишком большой для стандартного Telegram API (лимит 20 МБ)."
            ) from exc
        raise TelegramDownloadFailed(f"Telegram отклонил скачивание: {exc}") from exc
    except TimeoutError as exc:
        cleanup_temp(destination)
        raise TelegramDownloadFailed(
            f"Скачивание не уложилось в {timeout} с. Попробуйте ещё раз или загрузите файл через сайт."
        ) from exc
    except TelegramAPIError as exc:
        cleanup_temp(destination)
        raise TelegramDownloadFailed(f"Ошибка Telegram API: {exc}") from exc
    except OSError as exc:
        cleanup_temp(destination)
        raise TelegramDownloadFailed(f"Не удалось записать временный файл: {exc}") from exc

    if not destination.is_file() or destination.stat().st_size == 0:
        cleanup_temp(destination)
        raise TelegramDownloadFailed("Telegram вернул пустой файл.")

    return destination


def cleanup_temp(path: Path | str | None) -> None:
    """Удаляет временный файл после успешного или неуспешного скачивания."""
    if not path:
        return
    file_path = Path(path)
    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Не удалось удалить временный файл %s", file_path)


def format_file_size(size_bytes: int | None) -> str:
    """Форматирует размер файла в читаемый вид для ответа пользователю в Telegram."""
    if size_bytes is None or size_bytes < 0:
        return "неизвестный размер"
    if size_bytes < 1024:
        return f"{size_bytes} Б"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} КБ"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} МБ"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} ГБ"
