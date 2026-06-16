from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from apps.files.models import FileAsset
from apps.files.storage import LocalFileStorage

logger = logging.getLogger(__name__)


def build_poster_relative_path(owner_id: int, public_id) -> str:
    """Формирует относительный путь JPEG-постера для видео в приватном хранилище."""
    return f"uploads/user_{owner_id}/posters/{public_id}.jpg"


def generate_video_poster(asset: FileAsset, storage: LocalFileStorage | None = None) -> str | None:
    """Извлекает первый кадр видео через ffmpeg и сохраняет JPEG-постер; возвращает относительный путь."""
    if asset.category != FileAsset.Category.VIDEO or not asset.storage_path:
        return None

    storage = storage or LocalFileStorage()
    if shutil.which("ffmpeg") is None:
        logger.warning("ffmpeg не найден: обложка для видео %s не будет создана", asset.public_id)
        return None

    source_path = storage.resolve_private_path(asset.storage_path)
    if not source_path.is_file():
        logger.warning("Видеофайл не найден для постера: %s", asset.storage_path)
        return None

    relative_path = build_poster_relative_path(asset.owner_id, asset.public_id)
    poster_path = storage.resolve_private_path(relative_path)
    poster_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        "0",
        "-i",
        str(source_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(poster_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Не удалось создать постер для видео %s: %s", asset.public_id, exc)
        if poster_path.exists():
            poster_path.unlink(missing_ok=True)
        return None

    if not poster_path.is_file() or poster_path.stat().st_size == 0:
        logger.warning("ffmpeg не создал постер для видео %s", asset.public_id)
        return None

    asset.poster_path = relative_path
    asset.save(update_fields=["poster_path", "updated_at"])
    return relative_path
