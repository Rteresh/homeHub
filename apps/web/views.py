from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.contrib.auth import login
from django.http import Http404
from django.shortcuts import redirect
from django.views.generic import TemplateView

from apps.accounts.services import TelegramLoginService
from apps.web.services.log_viewer import DEFAULT_TAIL_LINES, MAX_TAIL_LINES, LogViewerService


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Доступ только для staff/superuser — как к ops-разделам на деплое."""

    def test_func(self):
        user = self.request.user
        return user.is_active and (user.is_staff or user.is_superuser)


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = "web/home.html"


class LaterView(LoginRequiredMixin, TemplateView):
    template_name = "web/later.html"


class LogViewerListView(StaffRequiredMixin, TemplateView):
    template_name = "web/logs_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["logs"] = LogViewerService.list_logs()
        context["logs_dir"] = str(LogViewerService.logs_dir())
        return context


class LogViewerDetailView(StaffRequiredMixin, TemplateView):
    template_name = "web/logs_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        slug = kwargs["slug"]
        if LogViewerService.resolve_slug(slug) is None:
            raise Http404("Журнал не найден")

        try:
            lines = int(self.request.GET.get("lines", DEFAULT_TAIL_LINES))
        except ValueError:
            lines = DEFAULT_TAIL_LINES

        log_info, content_lines = LogViewerService.tail(slug, lines=lines)
        context["log"] = log_info
        context["content_lines"] = content_lines
        context["lines"] = max(1, min(lines, MAX_TAIL_LINES))
        context["follow"] = self.request.GET.get("follow") == "1"
        context["all_logs"] = LogViewerService.list_logs()
        return context


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
