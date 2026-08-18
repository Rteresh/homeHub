from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.utils import timezone
from django.utils.text import get_valid_filename


class DirectUploadError(Exception):
    """Ошибка валидации пути или записи файла на сервер."""


@dataclass(frozen=True)
class DirectUploadResult:
    saved_path: Path
    original_name: str
    size_bytes: int


class DirectUploadService:
    """Записывает загруженные файлы в указанный каталог на сервере вне медиатеки HomeHub."""

    @staticmethod
    def _root_is_accessible(path: Path) -> bool:
        if path.is_dir():
            mode = os.R_OK | os.X_OK
            if os.access(path, os.W_OK):
                return True
            # /srv часто принадлежит root: запись возможна в подкаталоги, доступные пользователю.
            return os.access(path, mode)
        return os.access(path.parent if path.parent != path else path, os.W_OK)

    @classmethod
    def allowed_roots(cls) -> list[Path]:
        configured = getattr(settings, "HOMEHUB_DIRECT_UPLOAD_PATH_PREFIXES", None) or []
        if configured:
            return [Path(prefix).resolve() for prefix in configured]

        storage_root = Path(settings.HOMEHUB_STORAGE_ROOT).resolve()
        export_roots = [Path(prefix).resolve() for prefix in settings.OPS_EXPORT_PATH_PREFIXES]
        candidates = [storage_root, Path("/srv").resolve(), *export_roots]

        seen: set[Path] = set()
        usable: list[Path] = []
        for root in candidates:
            if root in seen:
                continue
            seen.add(root)
            if cls._root_is_accessible(root):
                usable.append(root)
        return usable

    @classmethod
    def validate_target_dir(cls, target_dir: str, *, create_missing: bool = True) -> Path:
        cleaned = target_dir.strip()
        if not cleaned:
            raise DirectUploadError("Укажите каталог на сервере, например /srv/incoming/docs.")
        if not cleaned.startswith("/"):
            raise DirectUploadError("Путь должен быть абсолютным и начинаться с /.")

        resolved = Path(cleaned).resolve()
        allowed_roots = cls.allowed_roots()
        if not any(resolved == root or resolved.is_relative_to(root) for root in allowed_roots):
            allowed = ", ".join(str(root) for root in allowed_roots)
            raise DirectUploadError(f"Путь должен быть внутри одного из разрешённых каталогов: {allowed}.")

        if resolved.is_file():
            raise DirectUploadError("Укажите каталог, а не файл.")

        if not resolved.is_dir():
            if not create_missing:
                raise DirectUploadError(f"Каталог не найден: {resolved}")
            try:
                resolved.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise DirectUploadError(f"Не удалось создать каталог {resolved}: {exc.strerror or exc}") from exc

        if not os.access(resolved, os.W_OK):
            raise DirectUploadError(f"Нет прав записи: {resolved}")
        return resolved

    @classmethod
    def save_upload(cls, target_dir: Path, uploaded_file) -> DirectUploadResult:
        safe_name = get_valid_filename(Path(uploaded_file.name).name) or "upload.bin"
        destination = target_dir / safe_name
        if destination.exists():
            raise DirectUploadError(f"Файл уже существует: {destination}")

        size_bytes = 0
        try:
            with destination.open("wb") as output:
                for chunk in uploaded_file.chunks():
                    size_bytes += len(chunk)
                    output.write(chunk)
        except OSError as exc:
            raise DirectUploadError(f"Не удалось записать файл {destination}: {exc.strerror or exc}") from exc

        return DirectUploadResult(saved_path=destination, original_name=uploaded_file.name, size_bytes=size_bytes)

    @classmethod
    def log_path(cls) -> Path:
        path = Path(settings.HOMEHUB_STORAGE_ROOT) / "logs" / "direct-upload.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def append_log(
        cls,
        *,
        user: AbstractBaseUser | None,
        target_dir: Path,
        results: list[DirectUploadResult],
        uploaded_at: datetime | None = None,
    ) -> None:
        username = getattr(user, "username", "unknown")
        moment = uploaded_at or timezone.now()
        lines = [
            f"\n{'=' * 60}",
            f"{moment.isoformat()} user={username} target={target_dir}",
        ]
        for item in results:
            lines.append(f"  + {item.saved_path} ({item.size_bytes} B, src={item.original_name})")
        with cls.log_path().open("a", encoding="utf-8") as log_file:
            log_file.write("\n".join(lines) + "\n")
