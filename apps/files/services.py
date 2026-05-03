import mimetypes
from io import BytesIO

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.db import transaction
from django.db.models import Q, QuerySet

from apps.files.models import FileAsset
from apps.files.storage import LocalFileStorage


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
        relative_path = storage.build_upload_path(asset.owner_id, original_name)
        size_bytes, checksum = storage.write_uploaded_file(relative_path, uploaded_file)

        asset.original_name = original_name
        asset.storage_path = relative_path
        asset.mime_type = mime_type
        if not asset.category or asset.category == FileAsset.Category.OTHER:
            asset.category = cls.detect_category(mime_type, original_name)
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

        return asset

    @classmethod
    def create_from_uploaded_file(cls, owner, uploaded_file, category: str = "") -> FileAsset:
        """Создаёт FileAsset для владельца `owner` из файла веб-формы или админки."""
        asset = FileAsset(
            owner=owner,
            source=FileAsset.Source.WEB,
            original_name="",
            storage_path="",
            category=category or FileAsset.Category.OTHER,
            status=FileAsset.Status.PENDING,
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
        )
        return cls.attach_uploaded_file(asset, BytesUpload(content, original_name, mime_type))
