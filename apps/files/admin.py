from django.contrib import admin

from apps.files.forms import FileAssetAdminForm
from apps.files.models import Album, FileAsset
from apps.files.services import FileIngestionService


@admin.register(Album)
class AlbumAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
    search_fields = ("name", "owner__username")
    readonly_fields = ("public_id", "created_at", "updated_at")


@admin.register(FileAsset)
class FileAssetAdmin(admin.ModelAdmin):
    form = FileAssetAdminForm
    list_display = ("original_name", "owner", "category", "status", "size_bytes", "source", "created_at")
    list_filter = ("category", "status", "source", "created_at")
    search_fields = ("original_name", "owner__username", "checksum", "telegram_file_id")
    readonly_fields = ("public_id", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        upload_file = form.cleaned_data.get("upload_file")
        if upload_file:
            obj.source = FileAsset.Source.WEB
            FileIngestionService.attach_uploaded_file(obj, upload_file)
            return
        super().save_model(request, obj, form, change)
