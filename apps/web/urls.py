from django.urls import path

from apps.web import views


urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("2server/", views.direct_upload, name="2server"),
    path("print/", views.print_document, name="print-document"),
    path("telegram-login/", views.telegram_login, name="telegram-login"),
    path("later/", views.LaterView.as_view(), name="later"),
    path("ops/logs/", views.LogViewerListView.as_view(), name="ops-logs"),
    path("ops/logs/<slug:slug>/", views.LogViewerDetailView.as_view(), name="ops-log-detail"),
    path("ops/scripts/", views.ScriptRunnerView.as_view(), name="ops-scripts"),
]
