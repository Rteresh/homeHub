from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from apps.files.forms import FileUploadForm
from apps.files.models import FileAsset
from apps.files.permissions import FileAccessService
from apps.files.services import FileIngestionService, FileQueryService
from apps.files.storage import LocalFileStorage, StoragePathError


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
            .filter(category__in=[FileAsset.Category.PHOTO, FileAsset.Category.VIDEO], status=FileAsset.Status.READY)
            .order_by("-created_at", "-id")
        )


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
            .filter(category__in=[FileAsset.Category.PHOTO, FileAsset.Category.VIDEO], status=FileAsset.Status.READY)
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
    if not asset.is_ready or asset.category not in {FileAsset.Category.PHOTO, FileAsset.Category.VIDEO}:
        raise Http404("Файл недоступен для предпросмотра.")

    storage = LocalFileStorage()
    try:
        file_handle = storage.open_for_read(asset.storage_path)
    except (FileNotFoundError, StoragePathError) as exc:
        raise Http404("Файл не найден в приватном хранилище.") from exc

    response = FileResponse(file_handle, content_type=asset.mime_type or "application/octet-stream")
    response["Content-Disposition"] = f'inline; filename="{asset.original_name}"'
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


@login_required
def upload_file(request):
    if request.method == "POST":
        form = FileUploadForm(request.POST, request.FILES)
        if form.is_valid():
            FileIngestionService.create_from_uploaded_file(
                owner=request.user,
                uploaded_file=form.cleaned_data["file"],
                category=form.cleaned_data.get("category", ""),
            )
            messages.success(request, "Файл загружен.")
            return redirect(reverse("file-list"))
    else:
        form = FileUploadForm()

    return render(request, "files/upload.html", {"form": form})
