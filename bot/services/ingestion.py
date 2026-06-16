from pathlib import Path

from apps.files.models import FileAsset
from apps.files.services import FileIngestionService


def save_telegram_payload(
    owner,
    content: bytes,
    original_name: str,
    mime_type: str,
    telegram_file_id: str,
    telegram_message_id: int | None,
) -> FileAsset:
    """Передаёт скачанные из Telegram bytes в общий сервис сохранения файлов и возвращает созданный FileAsset."""
    return FileIngestionService.create_from_bytes(
        owner=owner,
        content=content,
        original_name=original_name,
        mime_type=mime_type,
        source=FileAsset.Source.TELEGRAM,
        telegram_file_id=telegram_file_id,
        telegram_message_id=telegram_message_id,
    )


def save_telegram_file_from_path(
    owner,
    file_path: Path | str,
    original_name: str,
    mime_type: str,
    telegram_file_id: str,
    telegram_message_id: int | None,
    telegram_profile=None,
    album=None,
) -> FileAsset:
    """Сохраняет Telegram-файл с диска в приватное хранилище и создаёт запись FileAsset в БД."""
    resolved_album = album
    if resolved_album is None and telegram_profile is not None:
        profile = (
            type(telegram_profile)
            .objects.select_related("active_album")
            .filter(pk=telegram_profile.pk)
            .first()
        )
        resolved_album = profile.active_album if profile else None

    return FileIngestionService.create_from_file_path(
        owner=owner,
        file_path=file_path,
        original_name=original_name,
        mime_type=mime_type,
        source=FileAsset.Source.TELEGRAM,
        telegram_file_id=telegram_file_id,
        telegram_message_id=telegram_message_id,
        album=resolved_album,
    )


def find_existing_telegram_asset(owner, telegram_message_id: int | None) -> FileAsset | None:
    """Возвращает уже сохранённый файл по message_id, чтобы повторный update не создавал дубль."""
    if telegram_message_id is None:
        return None
    return (
        FileAsset.objects.filter(
            owner=owner,
            telegram_message_id=telegram_message_id,
            status=FileAsset.Status.READY,
        )
        .order_by("-id")
        .first()
    )
