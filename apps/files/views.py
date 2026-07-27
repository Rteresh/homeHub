from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import EmptyPage, Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from apps.files.albums import AlbumService, attach_cover_files
from apps.files.forms import FileUploadForm
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
PAGE_PARAM = "page"


def paginate_queryset(queryset, page_number: str | None, per_page: int):
    """Возвращает Page для queryset, чтобы шаблон мог рисовать стабильную пагинацию."""
    paginator = Paginator(queryset, per_page)
    try:
        page_obj = paginator.page(page_number or 1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    return page_obj


def page_window(page_obj, radius: int = 2) -> list[int]:
    """Строит компактное окно номеров страниц вокруг текущей для панели навигации."""
    start = max(page_obj.number - radius, 1)
    end = min(page_obj.number + radius, page_obj.paginator.num_pages)
    return list(range(start, end + 1))


def pagination_query(params) -> str:
    """Сохраняет активные фильтры в URL пагинации, исключая номер страницы."""
    query = params.copy()
    query.pop(PAGE_PARAM, None)
    encoded = query.urlencode()
    return f"&{encoded}" if encoded else ""

ALBUM_FILES_PAGE_SIZE = 60
MEDIA_STRIP_NEIGHBOR_COUNT = 6
PRIVATE_CACHE_MAX_AGE = 86400


def _cacheable_file_response(file_handle, *, content_type: str, filename: str, inline: bool = True) -> FileResponse:
    disposition = "inline" if inline else "attachment"
    response = FileResponse(file_handle, content_type=content_type)
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    response["Cache-Control"] = f"private, max-age={PRIVATE_CACHE_MAX_AGE}"
    return response


def _media_neighbor_filter_newer(current: FileAsset) -> Q:
    return Q(created_at__gt=current.created_at) | Q(created_at=current.created_at, id__gt=current.id)


def _media_neighbor_filter_older(current: FileAsset) -> Q:
    return Q(created_at__lt=current.created_at) | Q(created_at=current.created_at, id__lt=current.id)


def _media_navigation_context(base_queryset, current: FileAsset) -> dict[str, object]:
    newer_filter = _media_neighbor_filter_newer(current)
    older_filter = _media_neighbor_filter_older(current)

    previous_media = base_queryset.filter(newer_filter).order_by("created_at", "id").first()
    next_media = base_queryset.filter(older_filter).order_by("-created_at", "-id").first()

    newer_count = base_queryset.filter(newer_filter).count()
    newer_offset = max(0, newer_count - MEDIA_STRIP_NEIGHBOR_COUNT)
    newer_neighbors = list(
        base_queryset.filter(newer_filter).order_by("-created_at", "-id")[newer_offset : newer_offset + MEDIA_STRIP_NEIGHBOR_COUNT]
    )
    older_neighbors = list(base_queryset.filter(older_filter).order_by("-created_at", "-id")[:MEDIA_STRIP_NEIGHBOR_COUNT])
    media_strip = newer_neighbors + [current] + older_neighbors

    return {
        "previous_media": previous_media,
        "next_media": next_media,
        "media_strip": media_strip,
    }


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
        context["pagination_window"] = page_window(context["page_obj"])
        context["pagination_query"] = pagination_query(self.request.GET)
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
        context["pagination_window"] = page_window(context["page_obj"])
        context["pagination_query"] = pagination_query(self.request.GET)
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
        context.update(_media_navigation_context(self.get_queryset(), self.object))
        return context


@method_decorator(login_required, name="dispatch")
class AlbumListView(ListView):
    model = Album
    template_name = "files/album_list.html"
    context_object_name = "albums"
    paginate_by = 30

    def get_queryset(self):
        return AlbumService.list_for_user(self.request.user).annotate(
            file_count=Count("files", filter=Q(files__status=FileAsset.Status.READY))
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        attach_cover_files(list(context["albums"]))
        context["pagination_window"] = page_window(context["page_obj"])
        context["pagination_query"] = pagination_query(self.request.GET)
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
        page_obj = paginate_queryset(
            (
                FileQueryService.visible_to(self.request.user)
                .filter(album=self.object, status=FileAsset.Status.READY)
                .order_by("-created_at", "-id")
            ),
            self.request.GET.get(PAGE_PARAM),
            ALBUM_FILES_PAGE_SIZE,
        )
        context["album_files_page"] = page_obj
        context["album_files"] = page_obj.object_list
        context["page_obj"] = page_obj
        context["is_paginated"] = page_obj.paginator.num_pages > 1
        context["paginator"] = page_obj.paginator
        context["pagination_window"] = page_window(page_obj)
        context["pagination_query"] = pagination_query(self.request.GET)
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

    return _cacheable_file_response(
        file_handle,
        content_type=asset.mime_type or "application/octet-stream",
        filename=asset.original_name,
        inline=False,
    )


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

    return _cacheable_file_response(
        file_handle,
        content_type=asset.mime_type or "application/octet-stream",
        filename=asset.original_name,
    )


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

    return _cacheable_file_response(
        file_handle,
        content_type="image/jpeg",
        filename=f"{asset.public_id}.jpg",
    )


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
            created_assets: list[FileAsset] = []
            for uploaded_file in form.cleaned_data["files"]:
                created_assets.append(
                    FileIngestionService.create_from_uploaded_file(
                        owner=request.user,
                        uploaded_file=uploaded_file,
                        category=category,
                        album=album,
                    )
                )
            count = len(form.cleaned_data["files"])
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "uploaded_count": count,
                        "files": [
                            {
                                "public_id": str(asset.public_id),
                                "original_name": asset.original_name,
                                "category": asset.category,
                            }
                            for asset in created_assets
                        ],
                        "redirect_url": (
                            reverse("album-detail", kwargs={"public_id": album.public_id})
                            if album
                            else reverse("file-list")
                        ),
                    }
                )
            messages.success(request, f"Загружено файлов: {count}.")
            if album:
                return redirect(reverse("album-detail", kwargs={"public_id": album.public_id}))
            return redirect(reverse("file-list"))
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"errors": form.errors.get_json_data(), "non_field_errors": form.non_field_errors()}, status=400)
    else:
        form = FileUploadForm(user=request.user)

    return render(request, "files/upload.html", {"form": form})
