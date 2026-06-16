from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from apps.files.forms import FileUploadForm
from django.db.models import Count, Q

from apps.files.albums import AlbumService
from apps.files.models import Album, FileAsset
from apps.files.permissions import FileAccessService
from apps.files.services import BulkFileActionService, FileIngestionService, FileQueryService
from apps.files.storage import LocalFileStorage, StoragePathError

# Категории, которые показываются в медиатеке и отдаются через inline preview.
MEDIA_LIBRARY_CATEGORIES = (
    FileAsset.Category.PHOTO,
    FileAsset.Category.VIDEO,
    FileAsset.Category.AUDIO,
)


@method_decorator(login_required, name="dispatch")
class FileListView(ListView):
    model = FileAsset
    template_name = "files/file_list.html"
    context_object_name = "files"
    paginate_by = 30

    def get_queryset(self):
        return FileQueryService.from_request(self.request.user, self.request.GET)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = FileAsset.Category.choices
        context["statuses"] = FileAsset.Status.choices
        context["selected_category"] = self.request.GET.get("category", "")
        context["selected_status"] = self.request.GET.get("status", "")
        context["search_query"] = self.request.GET.get("q", "")
        context["selected_sort"] = self.request.GET.get("sort", "date")
        return context


@method_decorator(login_required, name="dispatch")
class MediaLibraryView(ListView):
    model = FileAsset
    template_name = "files/media_library.html"
    context_object_name = "media_files"
    paginate_by = 60

    def get_queryset(self):
        return (
            FileQueryService.visible_to(self.request.user)
            .filter(category__in=MEDIA_LIBRARY_CATEGORIES, status=FileAsset.Status.READY)
            .order_by("-created_at", "-id")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["selection_return_to"] = reverse("media-library")
        return context


@method_decorator(login_required, name="dispatch")
class MediaDetailView(DetailView):
    model = FileAsset
    template_name = "files/media_detail.html"
    context_object_name = "media_file"
    slug_field = "public_id"
    slug_url_kwarg = "public_id"

    def get_queryset(self):
        return (
            FileQueryService.visible_to(self.request.user)
            .filter(category__in=MEDIA_LIBRARY_CATEGORIES, status=FileAsset.Status.READY)
            .order_by("-created_at", "-id")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        media_queryset = list(self.get_queryset())
        current_index = next(
            (index for index, asset in enumerate(media_queryset) if asset.pk == self.object.pk),
            0,
        )
        context["previous_media"] = media_queryset[current_index - 1] if current_index > 0 else None
        context["next_media"] = media_queryset[current_index + 1] if current_index + 1 < len(media_queryset) else None
        context["media_strip"] = media_queryset[max(current_index - 6, 0) : current_index + 7]
        return context


def album_cover_file(album: Album) -> FileAsset | None:
    """Возвращает последний фото- или видеофайл альбома для обложки на списке альбомов."""
    return (
        album.files.filter(status=FileAsset.Status.READY)
        .filter(
            Q(category=FileAsset.Category.PHOTO)
            | Q(category=FileAsset.Category.VIDEO, poster_path__gt="")
            | Q(category=FileAsset.Category.VIDEO)
        )
        .order_by("-created_at", "-id")
        .first()
    )


@method_decorator(login_required, name="dispatch")
class AlbumListView(ListView):
    model = Album
    template_name = "files/album_list.html"
    context_object_name = "albums"
    paginate_by = 30

    def get_queryset(self):
        return (
            AlbumService.list_for_user(self.request.user)
            .annotate(file_count=Count("files", filter=Q(files__status=FileAsset.Status.READY)))
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for album in context["albums"]:
            album.cover_file = album_cover_file(album)
        return context


@method_decorator(login_required, name="dispatch")
class AlbumDetailView(DetailView):
    model = Album
    template_name = "files/album_detail.html"
    context_object_name = "album"
    slug_field = "public_id"
    slug_url_kwarg = "public_id"

    def get_queryset(self):
        return AlbumService.list_for_user(self.request.user).annotate(
            file_count=Count("files", filter=Q(files__status=FileAsset.Status.READY))
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["album_files"] = (
            FileQueryService.visible_to(self.request.user)
            .filter(album=self.object, status=FileAsset.Status.READY)
            .order_by("-created_at", "-id")
        )
        context["selection_return_to"] = reverse("album-detail", kwargs={"public_id": self.object.public_id})
        return context


@login_required
def download_file(request, public_id):
    asset = get_object_or_404(FileAsset, public_id=public_id)
    if not FileAccessService.can_download(request.user, asset):
        raise PermissionDenied("Недостаточно прав для скачивания файла.")
    if not asset.is_ready:
        raise Http404("Файл пока недоступен для скачивания.")

    storage = LocalFileStorage()
    try:
        file_handle = storage.open_for_read(asset.storage_path)
    except (FileNotFoundError, StoragePathError) as exc:
        raise Http404("Файл не найден в приватном хранилище.") from exc

    return FileResponse(file_handle, as_attachment=True, filename=asset.original_name)


@login_required
def preview_file(request, public_id):
    asset = get_object_or_404(FileAsset, public_id=public_id)
    if not FileAccessService.can_view(request.user, asset):
        raise PermissionDenied("Недостаточно прав для просмотра файла.")
    if not asset.is_ready or asset.category not in MEDIA_LIBRARY_CATEGORIES:
        raise Http404("Файл недоступен для предпросмотра.")

    storage = LocalFileStorage()
    try:
        file_handle = storage.open_for_read(asset.storage_path)
    except (FileNotFoundError, StoragePathError) as exc:
        raise Http404("Файл не найден в приватном хранилище.") from exc

    response = FileResponse(file_handle, content_type=asset.mime_type or "application/octet-stream")
    response["Content-Disposition"] = f'inline; filename="{asset.original_name}"'
    return response


@login_required
def poster_file(request, public_id):
    asset = get_object_or_404(FileAsset, public_id=public_id)
    if not FileAccessService.can_view(request.user, asset):
        raise PermissionDenied("Недостаточно прав для просмотра файла.")
    if not asset.is_ready or asset.category != FileAsset.Category.VIDEO or not asset.poster_path:
        raise Http404("Обложка видео недоступна.")

    storage = LocalFileStorage()
    try:
        file_handle = storage.open_for_read(asset.poster_path)
    except (FileNotFoundError, StoragePathError) as exc:
        raise Http404("Обложка видео не найдена в приватном хранилище.") from exc

    response = FileResponse(file_handle, content_type="image/jpeg")
    response["Content-Disposition"] = f'inline; filename="{asset.public_id}.jpg"'
    return response


@require_POST
@login_required
def delete_file(request, public_id):
    asset = get_object_or_404(FileAsset, public_id=public_id)
    if not FileAccessService.can_delete(request.user, asset):
        raise PermissionDenied("Недостаточно прав для удаления файла.")

    asset.status = FileAsset.Status.DELETED
    asset.save(update_fields=["status", "updated_at"])
    messages.success(request, "Файл удалён из списка.")
    return redirect(reverse("file-list"))


@require_POST
@login_required
def bulk_download_files(request):
    public_ids = BulkFileActionService.parse_public_ids(request.POST.getlist("public_ids"))
    if not public_ids:
        return HttpResponseBadRequest("Не выбрано ни одного файла.")

    storage = LocalFileStorage()
    assets = BulkFileActionService.downloadable_assets(request.user, public_ids, storage=storage)
    if not assets:
        raise Http404("Нет доступных для скачивания файлов.")

    if len(assets) == 1:
        asset = assets[0]
        try:
            file_handle = storage.open_for_read(asset.storage_path)
        except (FileNotFoundError, StoragePathError) as exc:
            raise Http404("Файл не найден в приватном хранилище.") from exc
        return FileResponse(file_handle, as_attachment=True, filename=asset.original_name)

    archive = BulkFileActionService.build_zip(assets, storage=storage)
    return FileResponse(
        archive,
        as_attachment=True,
        filename=BulkFileActionService.zip_filename(),
        content_type="application/zip",
    )


@require_POST
@login_required
def bulk_delete_files(request):
    public_ids = BulkFileActionService.parse_public_ids(request.POST.getlist("public_ids"))
    if not public_ids:
        return HttpResponseBadRequest("Не выбрано ни одного файла.")

    assets = BulkFileActionService.deletable_assets(request.user, public_ids)
    if not assets:
        messages.error(request, "Нет файлов, которые можно удалить.")
        return redirect(BulkFileActionService.resolve_return_url(request, request.POST.get("return_to", "")))

    for asset in assets:
        asset.status = FileAsset.Status.DELETED
        asset.save(update_fields=["status", "updated_at"])

    count = len(assets)
    if count == 1:
        messages.success(request, "Удалён 1 файл.")
    else:
        messages.success(request, f"Удалено файлов: {count}.")
    return redirect(BulkFileActionService.resolve_return_url(request, request.POST.get("return_to", "")))


@login_required
def upload_file(request):
    if request.method == "POST":
        uploaded_files = request.FILES.getlist("files")
        form = FileUploadForm(request.POST, user=request.user, uploaded_files=uploaded_files)
        if form.is_valid():
            album = form.cleaned_data.get("album")
            category = form.cleaned_data.get("category", "")
            for uploaded_file in form.cleaned_data["files"]:
                FileIngestionService.create_from_uploaded_file(
                    owner=request.user,
                    uploaded_file=uploaded_file,
                    category=category,
                    album=album,
                )
            count = len(form.cleaned_data["files"])
            messages.success(request, f"Загружено файлов: {count}.")
            if album:
                return redirect(reverse("album-detail", kwargs={"public_id": album.public_id}))
            return redirect(reverse("file-list"))
    else:
        form = FileUploadForm(user=request.user)

    return render(request, "files/upload.html", {"form": form})
