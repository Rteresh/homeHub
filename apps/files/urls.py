from django.urls import path

from apps.files import views


urlpatterns = [
    path("files/", views.FileListView.as_view(), name="file-list"),
    path("files/upload/", views.upload_file, name="file-upload"),
    path("media/", views.MediaLibraryView.as_view(), name="media-library"),
    path("media/<uuid:public_id>/", views.MediaDetailView.as_view(), name="media-detail"),
    path("files/<uuid:public_id>/preview/", views.preview_file, name="file-preview"),
    path("files/<uuid:public_id>/download/", views.download_file, name="file-download"),
    path("files/<uuid:public_id>/delete/", views.delete_file, name="file-delete"),
]
