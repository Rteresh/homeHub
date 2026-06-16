import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from bot.routers.album import main_keyboard
from asgiref.sync import sync_to_async
from django.conf import settings
from django.urls import reverse

from apps.accounts.models import TelegramProfile
from apps.accounts.services import TelegramLoginService
from apps.files.models import FileAsset
from bot.services.ingestion import find_existing_telegram_asset, save_telegram_file_from_path
from bot.services.telegram_download import (
    MediaPayload,
    TelegramDownloadFailed,
    TelegramFileTooLarge,
    cleanup_temp,
    download_telegram_file,
    extract_media_payload,
    format_file_size,
    is_file_too_large_for_standard_api,
)

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("start", "help"))
async def help_command(message: Message, django_user) -> None:
    """Отправляет краткую справку по командам и форматам данных, которые бот сохраняет в медиатеку."""
    limit_hint = (
        "Без Local Bot API Telegram ограничивает скачивание файлов 20 МБ.\n"
        "Большие файлы можно загрузить через сайт: /files/upload/\n"
    )
    if settings.TELEGRAM_LOCAL_MODE:
        limit_hint = "Включён Local Bot API: бот принимает файлы больше 20 МБ.\n"

    await message.answer(
        "HomeHub готов принимать фото, видео, GIF и файлы.\n"
        f"{limit_hint}"
        "/login — быстрая ссылка для входа на сайт\n"
        "/media — последние медиа из вашей медиатеки\n"
        "/dictionary или кнопка «Словарь» — 10 статей толкового словаря\n"
        "Кнопка «Альбом» — выбор или создание альбома для загрузок",
        reply_markup=main_keyboard(),
    )


@router.message(Command("login"))
async def login_command(message: Message, telegram_profile: TelegramProfile) -> None:
    """Создаёт одноразовую ссылку входа и отправляет её владельцу Telegram-профиля."""
    token = await sync_to_async(TelegramLoginService.create_login_token)(telegram_profile)
    login_url = f"{settings.SITE_BASE_URL}{reverse('telegram-login')}?token={token.token}"
    await message.answer(f"Ссылка для входа действует 10 минут:\n{login_url}")


@router.message(Command("media"))
async def media_command(message: Message, django_user) -> None:
    """Показывает последние сохранённые фото, видео и GIF пользователя без раскрытия внутренних путей хранения."""
    queryset = (
        FileAsset.objects.filter(
            owner=django_user,
            status=FileAsset.Status.READY,
            category__in=[FileAsset.Category.PHOTO, FileAsset.Category.VIDEO],
        )
        .order_by("-created_at", "-id")
        .values_list("original_name", "created_at")[:10]
    )
    rows = await sync_to_async(list)(queryset)
    if not rows:
        await message.answer("В медиатеке пока пусто.")
        return

    text = "\n".join(f"{created_at:%d.%m.%Y %H:%M} — {name}" for name, created_at in rows)
    await message.answer(text)


@router.message(F.photo | F.video | F.animation | F.document)
async def ingest_media(message: Message, bot, django_user, telegram_profile) -> None:
    """Скачивает Telegram-файл во временный каталог и сохраняет его в приватное хранилище HomeHub."""
    payload = extract_media_payload(message)
    if not payload:
        await message.answer("Не удалось найти файл в сообщении.")
        return

    existing = await sync_to_async(find_existing_telegram_asset)(django_user, message.message_id)
    if existing:
        await message.answer(f"Уже сохранено: {existing.original_name}")
        return

    if not settings.TELEGRAM_LOCAL_MODE and is_file_too_large_for_standard_api(payload.file_size):
        await message.answer(too_large_message(payload))
        return

    progress = await message.answer("Сохраняю файл, подождите...")
    temp_path: Path | None = None
    try:
        temp_path = await download_telegram_file(
            bot,
            payload.file_id,
            timeout=settings.TELEGRAM_DOWNLOAD_TIMEOUT,
        )

        def save_file():
            asset = save_telegram_file_from_path(
                owner=django_user,
                file_path=temp_path,
                original_name=payload.original_name,
                mime_type=payload.mime_type,
                telegram_file_id=payload.file_id,
                telegram_message_id=message.message_id,
                telegram_profile=telegram_profile,
            )
            album_name = asset.album.name if asset.album_id else ""
            return asset, album_name

        asset, album_name = await sync_to_async(save_file)()
    except TelegramFileTooLarge:
        logger.info(
            "Файл слишком большой для стандартного API update_id=%s user_id=%s size=%s",
            message.message_id,
            message.from_user.id if message.from_user else None,
            payload.file_size,
        )
        await progress.edit_text(too_large_message(payload))
        return
    except TelegramDownloadFailed as exc:
        logger.warning(
            "Ошибка скачивания Telegram update_id=%s user_id=%s size=%s: %s",
            message.message_id,
            message.from_user.id if message.from_user else None,
            payload.file_size,
            exc,
        )
        await progress.edit_text(str(exc))
        return
    except Exception:
        logger.exception(
            "Не удалось сохранить Telegram-файл update_id=%s user_id=%s size=%s",
            message.message_id,
            message.from_user.id if message.from_user else None,
            payload.file_size,
        )
        await progress.edit_text("Не удалось сохранить файл. Попробуйте ещё раз или загрузите через сайт.")
        return
    finally:
        cleanup_temp(temp_path)

    size_label = format_file_size(asset.size_bytes or payload.file_size)
    album_hint = f"\nАльбом: {album_name}" if album_name else ""
    await progress.edit_text(f"Сохранено: {asset.original_name} ({size_label}){album_hint}")


def too_large_message(payload: MediaPayload) -> str:
    """Формирует понятный ответ, когда Telegram не отдаёт файл боту из-за лимита 20 МБ."""
    size_label = format_file_size(payload.file_size)
    return (
        f"Файл «{payload.original_name}» ({size_label}) слишком большой для стандартного Telegram API "
        f"(лимит 20 МБ).\n"
        "Загрузите его через сайт: /files/upload/\n"
        "Или включите Local Bot API в настройках HomeHub."
    )
