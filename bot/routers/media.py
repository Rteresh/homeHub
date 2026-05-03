from io import BytesIO
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.conf import settings
from django.urls import reverse

from apps.accounts.models import TelegramProfile
from apps.accounts.services import TelegramLoginService
from apps.files.models import FileAsset
from bot.services.ingestion import save_telegram_payload

router = Router()


@router.message(Command("start", "help"))
async def help_command(message: Message, django_user) -> None:
    """Отправляет краткую справку по командам и форматам данных, которые бот сохраняет в медиатеку."""
    await message.answer(
        "HomeHub готов принимать фото, видео, GIF и файлы.\n"
        "/login — быстрая ссылка для входа на сайт\n"
        "/media — последние медиа из вашей медиатеки"
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
async def ingest_media(message: Message, bot, django_user) -> None:
    """Скачивает поддержанный Telegram payload и сохраняет его в приватное хранилище HomeHub."""
    payload = extract_payload(message)
    if not payload:
        await message.answer("Не удалось найти файл в сообщении.")
        return

    file_id, original_name, mime_type = payload
    buffer = BytesIO()
    await bot.download(file_id, destination=buffer)
    asset = await sync_to_async(save_telegram_payload)(
        owner=django_user,
        content=buffer.getvalue(),
        original_name=original_name,
        mime_type=mime_type,
        telegram_file_id=file_id,
        telegram_message_id=message.message_id,
    )
    await message.answer(f"Сохранено: {asset.original_name}")


def extract_payload(message: Message) -> tuple[str, str, str] | None:
    """Достаёт file_id, исходное имя и MIME-тип из фото, видео, GIF-анимации или документа Telegram."""
    if message.photo:
        photo = message.photo[-1]
        return photo.file_id, f"telegram_photo_{message.message_id}.jpg", "image/jpeg"
    if message.video:
        name = message.video.file_name or f"telegram_video_{message.message_id}.mp4"
        return message.video.file_id, Path(name).name, message.video.mime_type or "video/mp4"
    if message.animation:
        name = message.animation.file_name or f"telegram_gif_{message.message_id}.gif"
        return message.animation.file_id, Path(name).name, message.animation.mime_type or "image/gif"
    if message.document:
        name = message.document.file_name or f"telegram_file_{message.message_id}"
        return message.document.file_id, Path(name).name, message.document.mime_type or ""
    return None
