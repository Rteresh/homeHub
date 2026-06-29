from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.web.services.log_viewer import LogViewerService


class LogViewerServiceTests(TestCase):
    def test_tail_unknown_slug_raises(self):
        with self.assertRaises(ValueError):
            LogViewerService.tail("unknown-log")

    def test_tail_returns_last_lines(self):
        with TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir) / "logs"
            logs_dir.mkdir()
            log_path = logs_dir / "web.log"
            log_path.write_text("line1\nline2\nline3\n", encoding="utf-8")

            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                info, lines = LogViewerService.tail("web", lines=2)

            self.assertEqual(info.filename, "web.log")
            self.assertEqual(lines, ["line2", "line3"])


class LogViewerViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(username="staff", password="password", is_staff=True)
        self.user = User.objects.create_user(username="user", password="password")

    def test_anonymous_redirected_from_logs(self):
        response = self.client.get(reverse("ops-logs"))
        self.assertEqual(response.status_code, 302)

    def test_regular_user_forbidden(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("ops-logs"))
        self.assertEqual(response.status_code, 403)

    def test_staff_can_open_logs_list(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("ops-logs"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "gunicorn-access.log")

    def test_unknown_log_slug_returns_404(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("ops-log-detail", kwargs={"slug": "evil-log"}))
        self.assertEqual(response.status_code, 404)
