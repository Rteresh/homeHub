import json
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from apps.accounts.models import DictionaryEntry, DictionaryProgress, TelegramProfile


DICTIONARY_BATCH_SIZE = 10
DICTIONARY_SOURCE_PATH = settings.BASE_DIR / "static" / "dict" / "tolkovij_slovar.json"


@dataclass(frozen=True)
class DictionaryBatch:
    """Передаёт выбранную порцию словаря: статьи, границы выдачи и общее число записей."""

    entries: list[DictionaryEntry]
    start_position: int
    next_position: int
    total_count: int


def ensure_dictionary_loaded() -> int:
    """Загружает статьи из JSON в БД при первом обращении и возвращает общее число словарных записей."""
    current_count = DictionaryEntry.objects.count()
    if current_count:
        return current_count

    with transaction.atomic():
        current_count = DictionaryEntry.objects.count()
        if current_count:
            return current_count

        raw_entries = json.loads(DICTIONARY_SOURCE_PATH.read_text(encoding="utf-8"))
        objects = [
            DictionaryEntry(
                position=position,
                title=str(item.get("title", "")).strip(),
                sense=str(item.get("sense", "")).strip(),
            )
            for position, item in enumerate(raw_entries)
            if item.get("title") and item.get("sense")
        ]
        DictionaryEntry.objects.bulk_create(objects, batch_size=1000)
        return len(objects)


def get_next_dictionary_batch(profile: TelegramProfile) -> DictionaryBatch:
    """Возвращает следующую порцию словаря для профиля и сдвигает сохранённую позицию вперёд."""
    return _get_dictionary_batch(profile=profile, direction=1)


def get_previous_dictionary_batch(profile: TelegramProfile) -> DictionaryBatch:
    """Возвращает предыдущую порцию словаря для профиля и сохраняет позицию после показанного блока."""
    return _get_dictionary_batch(profile=profile, direction=-1)


def _get_dictionary_batch(profile: TelegramProfile, direction: int) -> DictionaryBatch:
    """Выбирает блок словаря по направлению: `1` берёт следующие слова, `-1` откатывает на прошлый блок."""
    total_count = ensure_dictionary_loaded()
    if not total_count:
        return DictionaryBatch(entries=[], start_position=0, next_position=0, total_count=0)

    with transaction.atomic():
        progress, _ = DictionaryProgress.objects.select_for_update().get_or_create(profile=profile)
        if direction < 0:
            start_position = max(progress.last_start_position - DICTIONARY_BATCH_SIZE, 0)
        else:
            start_position = 0 if progress.next_position >= total_count else progress.next_position

        entries = list(
            DictionaryEntry.objects.filter(
                position__gte=start_position,
                position__lt=start_position + DICTIONARY_BATCH_SIZE,
            ).order_by("position")
        )
        next_position = start_position + len(entries)
        progress.last_start_position = start_position
        progress.next_position = next_position
        progress.save(update_fields=["last_start_position", "next_position", "updated_at"])

    return DictionaryBatch(
        entries=entries,
        start_position=start_position,
        next_position=next_position,
        total_count=total_count,
    )
