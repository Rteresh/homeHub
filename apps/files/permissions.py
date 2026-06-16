from enum import StrEnum

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.db.models import Q

from apps.files.albums import AlbumService
from apps.files.models import FileAsset


class FileAction(StrEnum):
    VIEW = "view"
    PREVIEW = "preview"
    DOWNLOAD = "download"
    DELETE = "delete"
    EDIT_METADATA = "edit_metadata"


class FileAccessService:
    """Проверяет права пользователя на действие с FileAsset; используется views, API и ботом."""

    @staticmethod
    def can_access(user: AbstractBaseUser | AnonymousUser, asset: FileAsset, action: FileAction) -> bool:
        if not user or not user.is_authenticated or not user.is_active:
            return False
        if user.is_superuser or user.is_staff:
            return True
        if asset.owner_id == user.id:
            return True
        if action in {FileAction.VIEW, FileAction.PREVIEW, FileAction.DOWNLOAD} and asset.album_id:
            album_public_id = (
                asset.album.public_id
                if getattr(asset, "album", None) is not None
                else AlbumService.visible_to(user).filter(pk=asset.album_id).values_list("public_id", flat=True).first()
            )
            if album_public_id and AlbumService.get_for_user(user, album_public_id):
                return True
        if action == FileAction.EDIT_METADATA:
            return False
        return False

    @classmethod
    def can_view(cls, user: AbstractBaseUser | AnonymousUser, asset: FileAsset) -> bool:
        return cls.can_access(user, asset, FileAction.VIEW)

    @classmethod
    def can_download(cls, user: AbstractBaseUser | AnonymousUser, asset: FileAsset) -> bool:
        return cls.can_access(user, asset, FileAction.DOWNLOAD)

    @classmethod
    def can_delete(cls, user: AbstractBaseUser | AnonymousUser, asset: FileAsset) -> bool:
        return cls.can_access(user, asset, FileAction.DELETE)
