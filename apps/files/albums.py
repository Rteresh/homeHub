from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.db.models import Q, QuerySet

from apps.accounts.models import TelegramProfile
from apps.files.models import Album, FileAsset

ALBUM_COVER_FILE_FILTER = Q(category=FileAsset.Category.PHOTO) | Q(category=FileAsset.Category.VIDEO)


class AlbumService:
    """Операции с альбомами: общий доступ между пользователями HomeHub и выбор активного альбома в боте."""

    @staticmethod
    def homehub_member_ids() -> list[int]:
        """Возвращает id Django-пользователей с разрешённым Telegram-профилем — участников HomeHub."""
        return list(
            get_user_model()
            .objects.filter(is_active=True, telegram_profile__is_allowed=True)
            .values_list("id", flat=True)
        )

    @staticmethod
    def shared_album_ids() -> QuerySet:
        """Возвращает id альбомов, доступных всем участникам HomeHub."""
        member_ids = AlbumService.homehub_member_ids()
        return Album.objects.filter(owner_id__in=member_ids).values_list("id", flat=True)

    @staticmethod
    def visible_to(user: AbstractBaseUser | AnonymousUser):
        """Возвращает queryset альбомов: участники HomeHub видят альбомы друг друга."""
        queryset = Album.objects.select_related("owner", "owner__telegram_profile").order_by("-created_at", "-id")
        if not user or not getattr(user, "is_authenticated", False) or not user.is_active:
            return queryset.none()
        if user.is_superuser or user.is_staff:
            return queryset
        member_ids = AlbumService.homehub_member_ids()
        if user.id in member_ids:
            return queryset.filter(owner_id__in=member_ids)
        return queryset.filter(owner=user)

    @staticmethod
    def list_for_user(user: AbstractBaseUser | AnonymousUser):
        """Возвращает queryset альбомов, доступных пользователю на сайте или в боте."""
        return AlbumService.visible_to(user)

    @staticmethod
    def create_album(owner: AbstractBaseUser, name: str) -> Album:
        """Создаёт новый альбом с указанным именем для пользователя `owner`."""
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("Название альбома не может быть пустым.")
        return Album.objects.create(owner=owner, name=cleaned_name[:255])

    @staticmethod
    def get_for_user(user: AbstractBaseUser | AnonymousUser, public_id) -> Album | None:
        """Возвращает альбом по public_id, если он доступен текущему пользователю."""
        return AlbumService.visible_to(user).filter(public_id=public_id).first()

    @staticmethod
    def format_album_label(album: Album, user: AbstractBaseUser | AnonymousUser) -> str:
        """Формирует подпись альбома с именем владельца, если альбом принадлежит другому пользователю."""
        if album.owner_id == user.id:
            return album.name
        profile = getattr(album.owner, "telegram_profile", None)
        owner_label = profile.display_name if profile else album.owner.get_username()
        return f"{album.name} ({owner_label})"

    @staticmethod
    def set_active_album(profile: TelegramProfile, album: Album | None) -> TelegramProfile:
        """Сохраняет активный альбом профиля, если он доступен пользователю для загрузок."""
        if album is not None and AlbumService.get_for_user(profile.user, album.public_id) is None:
            raise PermissionError("Альбом недоступен для этого пользователя.")
        profile.active_album = album
        profile.save(update_fields=["active_album", "updated_at"])
        return profile


def attach_cover_files(albums: list[Album]) -> None:
    """Прикрепляет cover_file к каждому альому одним запросом (без N+1)."""
    if not albums:
        return

    album_ids = [album.pk for album in albums]
    cover_map: dict[int, FileAsset] = {}
    covers = (
        FileAsset.objects.filter(
            album_id__in=album_ids,
            status=FileAsset.Status.READY,
        )
        .filter(ALBUM_COVER_FILE_FILTER)
        .order_by("album_id", "-created_at", "-id")
    )
    for asset in covers:
        if asset.album_id not in cover_map:
            cover_map[asset.album_id] = asset

    for album in albums:
        album.cover_file = cover_map.get(album.pk)
