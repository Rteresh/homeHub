from __future__ import annotations

import mimetypes
import uuid
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import SpooledTemporaryFile

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from apps.files.albums import AlbumService
from apps.files.models import Album, FileAsset
from apps.files.permissions import FileAccessService
from apps.files.storage import LocalFileStorage, StoragePathError
from apps.files.video_poster import generate_video_poster

BULK_FILE_LIMIT = 100


class FileQueryService:
    """Формирует queryset файлов с учётом роли пользователя, фильтров и безопасной сортировки."""

    SORT_FIELDS = {
        "date": "-created_at",
        "name": "original_name",
        "size": "size_bytes",
        "type": "category",
        "user": "owner__username",
    }

    @staticmethod
    def visible_to(user: AbstractBaseUser | AnonymousUser) -> QuerySet[FileAsset]:
        queryset = FileAsset.objects.exclude(status=FileAsset.Status.DELETED).select_related("owner")
        if not user or not user.is_authenticated or not user.is_active:
            return queryset.none()
        if user.is_superuser or user.is_staff:
            return queryset
        member_ids = AlbumService.homehub_member_ids()
        if user.id in member_ids:
            shared_album_ids = Album.objects.filter(owner_id__in=member_ids).values_list("id", flat=True)
            return queryset.filter(Q(owner=user) | Q(album_id__in=shared_album_ids))
        return queryset.filter(owner=user)

    @classmethod
    def from_request(cls, user: AbstractBaseUser | AnonymousUser, params) -> QuerySet[FileAsset]:
        queryset = cls.visible_to(user)

        search = params.get("q", "").strip()
        if search:
            queryset = queryset.filter(
                Q(original_name__icontains=search)
                | Q(mime_type__icontains=search)
                | Q(checksum__icontains=search)
            )

        category = params.get("category", "").strip()
        if category in FileAsset.Category.values:
            queryset = queryset.filter(category=category)

        status = params.get("status", "").strip()
        if status in FileAsset.Status.values:
            queryset = queryset.filter(status=status)

        sort_key = params.get("sort", "date").strip()
        sort_field = cls.SORT_FIELDS.get(sort_key, cls.SORT_FIELDS["date"])
        if sort_key == "user" and not (user.is_staff or user.is_superuser):
            sort_field = cls.SORT_FIELDS["date"]
        return queryset.order_by(sort_field, "-id")


class FileIngestionService:
    """Сохраняет загруженный файл и метаданные как единую доменную операцию."""

    @staticmethod
    def detect_category(mime_type: str, original_name: str) -> str:
        """Определяет категорию файла по MIME-типу и расширению имени для фильтров и медиатеки."""
        guessed_type = mime_type or mimetypes.guess_type(original_name)[0] or ""
        if guessed_type.startswith("image/"):
            return FileAsset.Category.PHOTO
        if guessed_type.startswith("video/"):
            return FileAsset.Category.VIDEO
        if guessed_type.startswith("audio/"):
            return FileAsset.Category.AUDIO

        suffix = original_name.rsplit(".", maxsplit=1)[-1].lower() if "." in original_name else ""
        if suffix in {"zip", "rar", "7z", "tar", "gz", "bz2", "xz"}:
            return FileAsset.Category.ARCHIVE
        if suffix:
            return FileAsset.Category.DOCUMENT
        return FileAsset.Category.OTHER

    @classmethod
    def attach_uploaded_file(cls, asset: FileAsset, uploaded_file, storage: LocalFileStorage | None = None) -> FileAsset:
        """Записывает `uploaded_file` в storage и заполняет поля `asset`; при ошибке БД удаляет записанный файл."""
        storage = storage or LocalFileStorage()
        old_storage_path = ""
        if asset.pk:
            old_storage_path = FileAsset.objects.filter(pk=asset.pk).values_list("storage_path", flat=True).first() or ""

        original_name = uploaded_file.name
        mime_type = getattr(uploaded_file, "content_type", "") or mimetypes.guess_type(original_name)[0] or ""
        category = (
            asset.category
            if asset.category and asset.category != FileAsset.Category.OTHER
            else cls.detect_category(mime_type, original_name)
        )

        album_name = None
        album_fallback_id = ""
        if asset.album_id:
            album = asset.album
            album_name = album.name
            album_fallback_id = album.public_id.hex

        relative_path = storage.build_upload_path(
            asset.owner_id,
            original_name,
            category=category,
            album_name=album_name,
            album_fallback_id=album_fallback_id,
            uploaded_at=timezone.now(),
        )
        size_bytes, checksum = storage.write_uploaded_file(relative_path, uploaded_file)

        asset.original_name = original_name
        asset.storage_path = relative_path
        asset.mime_type = mime_type
        asset.category = category
        asset.size_bytes = size_bytes
        asset.checksum = checksum
        asset.source = asset.source or FileAsset.Source.WEB
        asset.status = FileAsset.Status.READY

        try:
            with transaction.atomic():
                asset.save()
        except Exception:
            storage.delete_file(relative_path)
            raise

        if old_storage_path and old_storage_path != relative_path:
            storage.delete_file(old_storage_path)

        if asset.category == FileAsset.Category.VIDEO:
            generate_video_poster(asset, storage=storage)

        return asset

    @classmethod
    def create_from_uploaded_file(
        cls,
        owner,
        uploaded_file,
        category: str = "",
        album: Album | None = None,
    ) -> FileAsset:
        """Создаёт FileAsset для владельца `owner` из файла веб-формы или админки."""
        asset = FileAsset(
            owner=owner,
            source=FileAsset.Source.WEB,
            original_name="",
            storage_path="",
            category=category or FileAsset.Category.OTHER,
            status=FileAsset.Status.PENDING,
            album=album,
        )
        return cls.attach_uploaded_file(asset, uploaded_file)

    @classmethod
    def create_from_bytes(
        cls,
        owner,
        content: bytes,
        original_name: str,
        mime_type: str = "",
        source: str = FileAsset.Source.TELEGRAM,
        telegram_file_id: str = "",
        telegram_message_id: int | None = None,
        album: Album | None = None,
    ) -> FileAsset:
        """Создаёт FileAsset из байтов внешнего источника; принимает владельца, имя, MIME и Telegram-метаданные."""

        class BytesUpload:
            """Даёт bytes-объекту интерфейс Django UploadedFile: имя, MIME-тип и итерацию chunk-ами."""

            def __init__(self, data: bytes, name: str, content_type: str) -> None:
                self._buffer = BytesIO(data)
                self.name = name
                self.content_type = content_type

            def chunks(self, chunk_size: int = 64 * 1024):
                while True:
                    chunk = self._buffer.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

        asset = FileAsset(
            owner=owner,
            source=source,
            original_name=original_name,
            storage_path="",
            category=cls.detect_category(mime_type, original_name),
            status=FileAsset.Status.PENDING,
            telegram_file_id=telegram_file_id,
            telegram_message_id=telegram_message_id,
            album=album,
        )
        return cls.attach_uploaded_file(asset, BytesUpload(content, original_name, mime_type))

    @classmethod
    def create_from_file_path(
        cls,
        owner,
        file_path: Path | str,
        original_name: str,
        mime_type: str = "",
        source: str = FileAsset.Source.TELEGRAM,
        telegram_file_id: str = "",
        telegram_message_id: int | None = None,
        album: Album | None = None,
    ) -> FileAsset:
        """Создаёт FileAsset из файла на диске, читая его chunk-ами без загрузки целиком в память."""

        class PathUpload:
            """Даёт файлу на диске интерфейс Django UploadedFile для потоковой записи в storage."""

            def __init__(self, path: Path, name: str, content_type: str) -> None:
                self._path = path
                self.name = name
                self.content_type = content_type

            def chunks(self, chunk_size: int = 64 * 1024):
                with self._path.open("rb") as source:
                    while True:
                        chunk = source.read(chunk_size)
                        if not chunk:
                            break
                        yield chunk

        resolved_path = Path(file_path)
        asset = FileAsset(
            owner=owner,
            source=source,
            original_name=original_name,
            storage_path="",
            category=cls.detect_category(mime_type, original_name),
            status=FileAsset.Status.PENDING,
            telegram_file_id=telegram_file_id,
            telegram_message_id=telegram_message_id,
            album=album,
        )
        return cls.attach_uploaded_file(asset, PathUpload(resolved_path, original_name, mime_type))


class BulkFileActionService:
    """Пакетное скачивание и удаление файлов с проверкой прав на каждый FileAsset."""

    @staticmethod
    def parse_public_ids(raw_ids: list[str]) -> list[uuid.UUID]:
        """Парсит список public_id из POST; пропускает пустые и невалидные UUID."""
        parsed: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        for raw_id in raw_ids:
            cleaned = raw_id.strip()
            if not cleaned:
                continue
            try:
                public_id = uuid.UUID(cleaned)
            except ValueError:
                continue
            if public_id in seen:
                continue
            seen.add(public_id)
            parsed.append(public_id)
            if len(parsed) >= BULK_FILE_LIMIT:
                break
        return parsed

    @classmethod
    def downloadable_assets(
        cls,
        user: AbstractBaseUser | AnonymousUser,
        public_ids: list[uuid.UUID],
        storage: LocalFileStorage | None = None,
    ) -> list[FileAsset]:
        """Возвращает готовые к скачиванию файлы, доступные пользователю и существующие в storage."""
        if not public_ids:
            return []

        storage = storage or LocalFileStorage()
        assets = list(
            FileAsset.objects.filter(public_id__in=public_ids, status=FileAsset.Status.READY).select_related("owner")
        )
        assets_by_id = {asset.public_id: asset for asset in assets}
        ordered_assets: list[FileAsset] = []
        for public_id in public_ids:
            asset = assets_by_id.get(public_id)
            if not asset or not FileAccessService.can_download(user, asset):
                continue
            try:
                if not storage.exists(asset.storage_path):
                    continue
            except StoragePathError:
                continue
            ordered_assets.append(asset)
        return ordered_assets

    @classmethod
    def deletable_assets(
        cls,
        user: AbstractBaseUser | AnonymousUser,
        public_ids: list[uuid.UUID],
    ) -> list[FileAsset]:
        """Возвращает файлы, которые пользователь может пометить как удалённые."""
        if not public_ids:
            return []

        assets = list(
            FileAsset.objects.filter(public_id__in=public_ids, status=FileAsset.Status.READY).select_related("owner")
        )
        assets_by_id = {asset.public_id: asset for asset in assets}
        ordered_assets: list[FileAsset] = []
        for public_id in public_ids:
            asset = assets_by_id.get(public_id)
            if asset and FileAccessService.can_delete(user, asset):
                ordered_assets.append(asset)
        return ordered_assets

    @staticmethod
    def unique_archive_name(original_name: str, used_names: set[str]) -> str:
        """Гарантирует уникальное имя файла внутри ZIP-архива."""
        candidate = original_name or "file"
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate

        suffix = Path(original_name).suffix
        stem = Path(original_name).stem or "file"
        index = 2
        while True:
            candidate = f"{stem}_{index}{suffix}"
            if candidate not in used_names:
                used_names.add(candidate)
                return candidate
            index += 1

    @classmethod
    def build_zip(cls, assets: list[FileAsset], storage: LocalFileStorage | None = None) -> SpooledTemporaryFile:
        """Собирает ZIP-архив из списка FileAsset, сохраняя порядок выбора."""
        storage = storage or LocalFileStorage()
        archive = SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b")
        used_names: set[str] = set()
        with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            for asset in assets:
                archive_name = cls.unique_archive_name(asset.original_name, used_names)
                with storage.open_for_read(asset.storage_path) as file_handle:
                    zip_file.writestr(archive_name, file_handle.read())
        archive.seek(0)
        return archive

    @staticmethod
    def zip_filename() -> str:
        """Формирует имя ZIP-архива с меткой времени."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"homehub-media-{timestamp}.zip"

    @staticmethod
    def resolve_return_url(request: HttpRequest, return_to: str) -> str:
        """Разрешает безопасный redirect после bulk delete: только медиатека или доступный альбом."""
        cleaned = return_to.strip()
        if cleaned == reverse("media-library"):
            return cleaned
        album_detail_prefix = "/albums/"
        if cleaned.startswith(album_detail_prefix):
            public_id_part = cleaned.removeprefix(album_detail_prefix).strip("/")
            try:
                album_public_id = uuid.UUID(public_id_part)
            except ValueError:
                return reverse("media-library")
            if AlbumService.list_for_user(request.user).filter(public_id=album_public_id).exists():
                return reverse("album-detail", kwargs={"public_id": album_public_id})
        return reverse("media-library")
