from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.web.services.log_viewer import LogViewerService
from apps.web.services.script_runner import ScriptRunnerError, ScriptRunnerService
from homehub.settings import resolve_storage_root


class StorageRootTests(SimpleTestCase):
    def test_maps_host_path_to_container_mount_in_docker(self):
        with TemporaryDirectory() as tmp_dir:
            mount = Path(tmp_dir) / "app_storage"
            mount.mkdir()
            resolved = resolve_storage_root(
                env={"HOMEHUB_STORAGE_ROOT": "/srv/storage/homehub"},
                in_docker=True,
                docker_storage=mount,
            )
            self.assertEqual(resolved, mount.resolve())


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


class ScriptRunnerServiceTests(TestCase):
    def test_ops_script_env_sets_skip_and_storage_from_settings(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir) / "storage"):
                env = ScriptRunnerService._ops_script_env()
            self.assertEqual(env["HOMEHUB_SKIP_HOST_ENV"], "1")
            self.assertEqual(env["HOMEHUB_STORAGE_ROOT"], str(Path(tmp_dir) / "storage"))

    def test_unknown_slug_raises(self):
        with self.assertRaises(ScriptRunnerError):
            ScriptRunnerService.run("evil-script")

    def test_validate_export_target_rejects_bad_prefix(self):
        with self.assertRaises(ScriptRunnerError):
            ScriptRunnerService.validate_export_target("/tmp/usb")

    def test_validate_export_target_accepts_media(self):
        with TemporaryDirectory() as tmp_dir:
            media_root = Path(tmp_dir) / "usb"
            media_root.mkdir(parents=True)
            with override_settings(OPS_EXPORT_PATH_PREFIXES=[tmp_dir]):
                resolved = ScriptRunnerService.validate_export_target(str(media_root))
            self.assertEqual(resolved, media_root.resolve())


class ScriptRunnerViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(username="staff", password="password", is_staff=True)
        self.user = User.objects.create_user(username="user", password="password")

    def test_anonymous_redirected(self):
        response = self.client.get(reverse("ops-scripts"))
        self.assertEqual(response.status_code, 302)

    def test_regular_user_forbidden(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("ops-scripts"))
        self.assertEqual(response.status_code, 403)

    def test_staff_can_open_scripts_page(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("ops-scripts"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "backup_homehub.sh")

    @patch("apps.web.services.script_runner.subprocess.run")
    def test_staff_can_run_backup_script(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "ok"
        mock_run.return_value.stderr = ""

        with TemporaryDirectory() as tmp_dir:
            with override_settings(HOMEHUB_STORAGE_ROOT=Path(tmp_dir)):
                self.client.force_login(self.staff)
                response = self.client.post(reverse("ops-scripts"), {"script": "backup-homehub"})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(mock_run.called)
        env = mock_run.call_args.kwargs["env"]
        self.assertEqual(env["HOMEHUB_SKIP_HOST_ENV"], "1")
        self.assertEqual(env["HOMEHUB_STORAGE_ROOT"], str(Path(tmp_dir).resolve()))
