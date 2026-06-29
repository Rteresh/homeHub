from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.services import TelegramLoginService
from apps.web.mixins import StaffRequiredMixin
from apps.web.services.log_viewer import DEFAULT_TAIL_LINES, MAX_TAIL_LINES, LogViewerService
from apps.web.services.script_runner import RUN_TIMEOUT_SEC, ScriptRunnerError, ScriptRunnerService


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


class ScriptRunnerView(StaffRequiredMixin, View):
    """Выбор whitelisted скрипта и запуск по кнопке; результат — на той же странице."""

    template_name = "web/ops_scripts.html"
    session_result_key = "ops_script_result"

    def get(self, request):
        last_result = request.session.pop(self.session_result_key, None)
        return render(
            request,
            self.template_name,
            {
                "scripts": ScriptRunnerService.list_scripts(),
                "last_result": last_result,
                "timeout_sec": RUN_TIMEOUT_SEC,
            },
        )

    def post(self, request):
        slug = request.POST.get("script", "").strip()
        target_dir = request.POST.get("target_dir", "").strip()
        dry_run = request.POST.get("dry_run") == "1"

        if not slug:
            messages.error(request, "Выберите скрипт.")
            return redirect("ops-scripts")

        try:
            result = ScriptRunnerService.run(
                slug,
                target_dir=target_dir,
                dry_run=dry_run,
                user=request.user,
            )
            request.session[self.session_result_key] = {
                "slug": result.slug,
                "label": result.label,
                "command": result.command,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "ok": result.ok,
                "timed_out": result.timed_out,
                "duration_sec": round(result.duration_sec, 1),
            }
            if result.ok:
                messages.success(request, f"Скрипт «{result.label}» завершён успешно.")
            else:
                messages.error(request, f"Скрипт «{result.label}» завершился с ошибкой (код {result.exit_code}).")
        except ScriptRunnerError as exc:
            messages.error(request, str(exc))

        return redirect("ops-scripts")


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
