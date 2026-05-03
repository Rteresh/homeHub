from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import TemplateView

from apps.accounts.services import TelegramLoginService


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = "web/home.html"


class LaterView(LoginRequiredMixin, TemplateView):
    template_name = "web/later.html"


def telegram_login(request):
    """Авторизует пользователя по одноразовому токену из Telegram и переводит его в основной раздел файлов."""
    raw_token = request.GET.get("token", "").strip()
    login_token = TelegramLoginService.consume_token(raw_token)
    if not login_token:
        messages.error(request, "Ссылка Telegram-входа истекла или уже была использована.")
        return redirect("login")

    login(request, login_token.profile.user)
    messages.success(request, "Вход через Telegram выполнен.")
    return redirect("media-library")
