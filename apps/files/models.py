import uuid

from django.conf import settings
from django.db import models


class Album(models.Model):
    """Группирует файлы пользователя в именованную коллекцию для бота и сайта."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="albums")
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["owner", "-created_at"]),
        ]
        ordering = ["-created_at"]
        verbose_name = "Альбом"
        verbose_name_plural = "Альбомы"

    def __str__(self) -> str:
        return self.name


class FileAsset(models.Model):
    """Хранит метаданные приватного файла; физический файл лежит в HOMEHUB_STORAGE_ROOT."""

    class Source(models.TextChoices):
        TELEGRAM = "telegram", "Telegram"
        WEB = "web", "Web"
        SYSTEM = "system", "System"

    class Category(models.TextChoices):
        PHOTO = "photo", "Фото"
        VIDEO = "video", "Видео"
        AUDIO = "audio", "Аудио"
        DOCUMENT = "document", "Документ"
        ARCHIVE = "archive", "Архив"
        OTHER = "other", "Другое"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает обработки"
        READY = "ready", "Готов"
        FAILED = "failed", "Ошибка"
        DELETED = "deleted", "Удалён"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="file_assets")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.WEB)
    original_name = models.CharField(max_length=255, blank=True)
    storage_path = models.CharField(max_length=1024, blank=True)
    mime_type = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    size_bytes = models.PositiveBigIntegerField(default=0)
    checksum = models.CharField(max_length=128, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    telegram_file_id = models.CharField(max_length=255, blank=True)
    telegram_message_id = models.BigIntegerField(blank=True, null=True)
    album = models.ForeignKey(
        Album,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="files",
    )
    poster_path = models.CharField(max_length=1024, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["owner", "-created_at"]),
            models.Index(fields=["category", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["album", "-created_at"]),
        ]
        ordering = ["-created_at"]
        verbose_name = "Файл"
        verbose_name_plural = "Файлы"

    def __str__(self) -> str:
        return self.original_name

    @property
    def is_ready(self) -> bool:
        return self.status == self.Status.READY

    @property
    def size_mb(self) -> float:
        """Размер файла в мегабайтах (1 МБ = 1024² байт)."""
        return self.size_bytes / (1024 * 1024)


class PrintJob(models.Model):
    """Сохраняет результат запроса и защищает печать от повторного POST или Telegram update."""

    class Status(models.TextChoices):
        PREPARING = "preparing", "Подготовка (повторная печать заблокирована)"
        SUBMITTED = "submitted", "Передано в очередь принтера"
        FAILED = "failed", "Ошибка"
        UNKNOWN = "unknown", "Проверьте очередь принтера перед повтором"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="print_jobs")
    request_id = models.UUIDField(default=uuid.uuid4)
    original_name = models.CharField(max_length=255)
    copies = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PREPARING)
    cups_job_id = models.CharField(max_length=255, blank=True)
    error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["owner", "request_id"], name="unique_print_request")]


class PrintIntent(models.Model):
    """Хранит ожидание следующего документа в конкретном Telegram-чате с ограничением по времени."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    chat_id = models.BigIntegerField()
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "chat_id"], name="unique_print_intent")]
