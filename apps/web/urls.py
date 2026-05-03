from django.urls import path

from apps.web import views


urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("telegram-login/", views.telegram_login, name="telegram-login"),
    path("later/", views.LaterView.as_view(), name="later"),
]
