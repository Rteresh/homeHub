from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.services import TelegramLoginService
from apps.web.forms import DirectUploadForm
from apps.web.mixins import StaffRequiredMixin
from apps.web.services.direct_upload import DirectUploadError, DirectUploadService
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


@login_required
def direct_upload(request):
    """Выгружает файлы с клиентского устройства в указанный каталог на сервере (вне медиатеки)."""
    allowed_roots = [str(root) for root in DirectUploadService.allowed_roots()]

    if request.method == "POST":
        uploaded_files = request.FILES.getlist("files")
        form = DirectUploadForm(request.POST, uploaded_files=uploaded_files)
        if form.is_valid():
            try:
                target_dir = DirectUploadService.validate_target_dir(form.cleaned_data["target_dir"])
            except DirectUploadError as exc:
                form.add_error("target_dir", str(exc))
            else:
                saved_results = []
                try:
                    for uploaded_file in form.cleaned_data["files"]:
                        saved_results.append(DirectUploadService.save_upload(target_dir, uploaded_file))
                except DirectUploadError as exc:
                    if request.headers.get("x-requested-with") == "XMLHttpRequest":
                        return JsonResponse(
                            {"non_field_errors": [str(exc)], "saved_count": len(saved_results)},
                            status=400,
                        )
                    form.add_error(None, str(exc))
                else:
                    DirectUploadService.append_log(
                        user=request.user,
                        target_dir=target_dir,
                        results=saved_results,
                    )
                    count = len(saved_results)
                    if request.headers.get("x-requested-with") == "XMLHttpRequest":
                        last = saved_results[-1]
                        return JsonResponse(
                            {
                                "uploaded_count": count,
                                "saved_path": str(last.saved_path),
                                "target_dir": str(target_dir),
                            }
                        )
                    if count == 1:
                        messages.success(request, f"Файл выгружен: {saved_results[0].saved_path}")
                    else:
                        messages.success(request, f"Выгружено файлов: {count} в {target_dir}")
                    return redirect("2server")

        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"errors": form.errors.get_json_data(), "non_field_errors": form.non_field_errors()}, status=400)
    else:
        form = DirectUploadForm()

    return render(
        request,
        "web/direct_upload.html",
        {"form": form, "allowed_roots": allowed_roots},
    )


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
