from django.urls import path

from apps.web import views


urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("telegram-login/", views.telegram_login, name="telegram-login"),
    path("later/", views.LaterView.as_view(), name="later"),
    path("ops/logs/", views.LogViewerListView.as_view(), name="ops-logs"),
    path("ops/logs/<slug:slug>/", views.LogViewerDetailView.as_view(), name="ops-log-detail"),
]
