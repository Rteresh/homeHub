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
