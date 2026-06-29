from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.utils import timezone
from django.utils.text import get_valid_filename, slugify


class StoragePathError(ValueError):
    """Сообщает, что относительный путь файла небезопасен или выходит за пределы приватного хранилища."""


def _slugify_album_name(name: str, fallback_id: str = "") -> str:
    """Превращает название альбома в безопасный сегмент пути; при пустом slug использует fallback_id."""
    album_slug = slugify(name)
    if album_slug:
        return album_slug
    if fallback_id:
        return f"album-{fallback_id[:8]}"
    return "album"


class LocalFileStorage:
    """Работает с приватным файловым хранилищем HomeHub и не принимает абсолютные клиентские пути."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or settings.HOMEHUB_STORAGE_ROOT).resolve()

    def resolve_private_path(self, relative_path: str) -> Path:
        normalized_path = Path(relative_path)
        if normalized_path.is_absolute():
            raise StoragePathError("Абсолютные пути запрещены для приватного хранилища.")

        resolved_path = (self.root / normalized_path).resolve()
        if not resolved_path.is_relative_to(self.root):
            raise StoragePathError("Путь файла выходит за пределы приватного хранилища.")
        return resolved_path

    def open_for_read(self, relative_path: str):
        file_path = self.resolve_private_path(relative_path)
        return file_path.open("rb")

    def exists(self, relative_path: str) -> bool:
        return self.resolve_private_path(relative_path).is_file()

    def build_upload_path(
        self,
        owner_id: int,
        original_name: str,
        *,
        category: str = "other",
        album_name: str | None = None,
        album_fallback_id: str = "",
        uploaded_at: datetime | None = None,
    ) -> str:
        """Создаёт относительный путь: альбом → albums/{slug}/{category}/, иначе user/{date}/{category}/."""
        safe_name = get_valid_filename(Path(original_name).name) or "upload.bin"
        file_name = f"{uuid4().hex}_{safe_name}"
        safe_category = category or "other"

        if album_name is not None:
            album_slug = _slugify_album_name(album_name, album_fallback_id)
            return f"albums/{album_slug}/{safe_category}/{file_name}"

        upload_moment = uploaded_at or timezone.now()
        if timezone.is_naive(upload_moment):
            upload_moment = timezone.make_aware(upload_moment, timezone.get_current_timezone())
        date_folder = timezone.localtime(upload_moment).strftime("%Y-%m-%d")
        return f"uploads/user_{owner_id}/{date_folder}/{safe_category}/{file_name}"

    def write_uploaded_file(self, relative_path: str, uploaded_file) -> tuple[int, str]:
        """Записывает Django UploadedFile в приватное хранилище и возвращает размер в байтах и SHA-256 checksum."""
        import hashlib

        file_path = self.resolve_private_path(relative_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        size_bytes = 0
        checksum = hashlib.sha256()
        with file_path.open("wb") as destination:
            for chunk in uploaded_file.chunks():
                size_bytes += len(chunk)
                checksum.update(chunk)
                destination.write(chunk)

        return size_bytes, checksum.hexdigest()

    def delete_file(self, relative_path: str) -> None:
        """Удаляет файл внутри приватного хранилища; отсутствие файла считается уже достигнутым состоянием."""
        file_path = self.resolve_private_path(relative_path)
        try:
            file_path.unlink()
        except FileNotFoundError:
            return
