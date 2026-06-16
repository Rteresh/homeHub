from django.urls import path

from apps.files import views


urlpatterns = [
    path("files/", views.FileListView.as_view(), name="file-list"),
    path("files/upload/", views.upload_file, name="file-upload"),
    path("albums/", views.AlbumListView.as_view(), name="album-list"),
    path("albums/<uuid:public_id>/", views.AlbumDetailView.as_view(), name="album-detail"),
    path("media/", views.MediaLibraryView.as_view(), name="media-library"),
    path("media/bulk-download/", views.bulk_download_files, name="media-bulk-download"),
    path("media/bulk-delete/", views.bulk_delete_files, name="media-bulk-delete"),
    path("media/<uuid:public_id>/", views.MediaDetailView.as_view(), name="media-detail"),
    path("files/<uuid:public_id>/preview/", views.preview_file, name="file-preview"),
    path("files/<uuid:public_id>/poster/", views.poster_file, name="file-poster"),
    path("files/<uuid:public_id>/download/", views.download_file, name="file-download"),
    path("files/<uuid:public_id>/delete/", views.delete_file, name="file-delete"),
]
