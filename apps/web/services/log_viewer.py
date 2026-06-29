from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.utils import timezone

# ponytail: фиксированный whitelist имён — без произвольных путей с диска
LOG_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("web", "web.log", "Сайт (runserver)"),
    ("gunicorn-access", "gunicorn-access.log", "Сайт: HTTP access"),
    ("gunicorn-error", "gunicorn-error.log", "Сайт: ошибки gunicorn"),
    ("bot", "bot.log", "Telegram-бот"),
    ("backup", "backup.log", "Скрипт backup"),
    ("export-storage", "export-storage.log", "Выгрузка storage"),
    ("export-backups", "export-backups.log", "Выгрузка backups"),
    ("ops-scripts", "ops-scripts.log", "Ops: запуск скриптов"),
)

LOG_SLUGS = {slug for slug, _, _ in LOG_SOURCES}
MAX_TAIL_LINES = 2000
DEFAULT_TAIL_LINES = 200


@dataclass(frozen=True)
class LogFileInfo:
    """Метаданные одного журнала из whitelist для страницы ops/logs."""

    slug: str
    filename: str
    label: str
    path: Path
    size_bytes: int
    updated_at: datetime | None
    exists: bool


class LogViewerService:
    """Читает tail журналов из HOMEHUB_STORAGE_ROOT/logs; только staff через view."""

    @staticmethod
    def logs_dir() -> Path:
        return Path(settings.HOMEHUB_STORAGE_ROOT).resolve() / "logs"

    @classmethod
    def resolve_slug(cls, slug: str) -> tuple[str, str, str] | None:
        for item in LOG_SOURCES:
            if item[0] == slug:
                return item
        return None

    @classmethod
    def list_logs(cls) -> list[LogFileInfo]:
        logs_dir = cls.logs_dir()
        items: list[LogFileInfo] = []
        for slug, filename, label in LOG_SOURCES:
            path = logs_dir / filename
            stat = path.stat() if path.is_file() else None
            updated_at = None
            size_bytes = 0
            exists = path.is_file()
            if stat is not None:
                size_bytes = stat.st_size
                updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone())
            items.append(
                LogFileInfo(
                    slug=slug,
                    filename=filename,
                    label=label,
                    path=path,
                    size_bytes=size_bytes,
                    updated_at=updated_at,
                    exists=exists,
                )
            )
        return items

    @classmethod
    def tail(cls, slug: str, lines: int = DEFAULT_TAIL_LINES) -> tuple[LogFileInfo, list[str]]:
        source = cls.resolve_slug(slug)
        if source is None:
            raise ValueError(f"Неизвестный журнал: {slug}")

        slug_name, filename, label = source
        path = cls.logs_dir() / filename
        safe_lines = max(1, min(lines, MAX_TAIL_LINES))
        content_lines = cls._read_tail(path, safe_lines) if path.is_file() else []

        stat = path.stat() if path.is_file() else None
        info = LogFileInfo(
            slug=slug_name,
            filename=filename,
            label=label,
            path=path,
            size_bytes=stat.st_size if stat else 0,
            updated_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()) if stat else None,
            exists=path.is_file(),
        )
        return info, content_lines

    @staticmethod
    def _read_tail(path: Path, max_lines: int) -> list[str]:
        """Возвращает последние `max_lines` строк файла без чтения всего файла в память."""
        block_size = 8192
        data = b""
        with path.open("rb") as source:
            source.seek(0, 2)
            position = source.tell()
            while position > 0 and data.count(b"\n") <= max_lines:
                read_size = min(block_size, position)
                position -= read_size
                source.seek(position)
                data = source.read(read_size) + data
        text = data.decode("utf-8", errors="replace")
        return text.splitlines()[-max_lines:]
