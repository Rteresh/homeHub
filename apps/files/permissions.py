from enum import StrEnum

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser

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
        if action == FileAction.EDIT_METADATA:
            return False
        return asset.owner_id == user.id

    @classmethod
    def can_view(cls, user: AbstractBaseUser | AnonymousUser, asset: FileAsset) -> bool:
        return cls.can_access(user, asset, FileAction.VIEW)

    @classmethod
    def can_download(cls, user: AbstractBaseUser | AnonymousUser, asset: FileAsset) -> bool:
        return cls.can_access(user, asset, FileAction.DOWNLOAD)

    @classmethod
    def can_delete(cls, user: AbstractBaseUser | AnonymousUser, asset: FileAsset) -> bool:
        return cls.can_access(user, asset, FileAction.DELETE)
