from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.web.services.direct_upload import DirectUploadError, DirectUploadService
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


class DirectUploadServiceTests(TestCase):
    def test_validate_target_dir_rejects_path_outside_allowed_roots(self):
        with self.assertRaises(DirectUploadError):
            DirectUploadService.validate_target_dir("/tmp/evil")

    def test_allowed_roots_skips_non_writable_defaults(self):
        with TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir) / "storage"
            storage_root.mkdir()
            with override_settings(HOMEHUB_STORAGE_ROOT=storage_root, HOMEHUB_DIRECT_UPLOAD_PATH_PREFIXES=[]):
                roots = DirectUploadService.allowed_roots()
            self.assertIn(storage_root.resolve(), roots)

    def test_validate_target_dir_reports_permission_error(self):
        with TemporaryDirectory() as tmp_dir:
            blocked_root = Path(tmp_dir) / "blocked"
            blocked_root.mkdir(mode=0o555)
            target = blocked_root / "incoming"
            try:
                with override_settings(HOMEHUB_DIRECT_UPLOAD_PATH_PREFIXES=[str(blocked_root)]):
                    with self.assertRaises(DirectUploadError) as ctx:
                        DirectUploadService.validate_target_dir(str(target))
                self.assertIn("создать каталог", str(ctx.exception).lower())
            finally:
                blocked_root.chmod(0o755)

    def test_validate_target_dir_accepts_path_under_srv_prefix(self):
        with TemporaryDirectory() as tmp_dir:
            srv_root = Path(tmp_dir) / "srv" / "incoming"
            srv_root.mkdir(parents=True)
            with override_settings(HOMEHUB_DIRECT_UPLOAD_PATH_PREFIXES=[str(Path(tmp_dir) / "srv")]):
                resolved = DirectUploadService.validate_target_dir(str(srv_root))
            self.assertEqual(resolved, srv_root.resolve())

    def test_save_upload_writes_file(self):
        with TemporaryDirectory() as tmp_dir:
            upload_root = Path(tmp_dir) / "uploads"
            upload_root.mkdir()
            with override_settings(HOMEHUB_DIRECT_UPLOAD_PATH_PREFIXES=[str(upload_root)]):
                target_dir = DirectUploadService.validate_target_dir(str(upload_root))
                uploaded = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
                result = DirectUploadService.save_upload(target_dir, uploaded)

            self.assertTrue(result.saved_path.is_file())
            self.assertEqual(result.saved_path.read_bytes(), b"hello")
            self.assertEqual(result.size_bytes, 5)

    def test_save_upload_rejects_existing_file(self):
        with TemporaryDirectory() as tmp_dir:
            upload_root = Path(tmp_dir) / "uploads"
            upload_root.mkdir()
            existing = upload_root / "note.txt"
            existing.write_text("old", encoding="utf-8")
            with override_settings(HOMEHUB_DIRECT_UPLOAD_PATH_PREFIXES=[str(upload_root)]):
                target_dir = DirectUploadService.validate_target_dir(str(upload_root))
                uploaded = SimpleUploadedFile("note.txt", b"new", content_type="text/plain")
                with self.assertRaises(DirectUploadError):
                    DirectUploadService.save_upload(target_dir, uploaded)


class DirectUploadViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="user", password="password")

    def test_upload_permission_denied_returns_400_not_500(self):
        with TemporaryDirectory() as tmp_dir:
            blocked_root = Path(tmp_dir) / "blocked"
            blocked_root.mkdir(mode=0o555)
            storage_root = Path(tmp_dir) / "storage"
            storage_root.mkdir()
            target = blocked_root / "incoming"
            try:
                with override_settings(
                    HOMEHUB_STORAGE_ROOT=storage_root,
                    HOMEHUB_DIRECT_UPLOAD_PATH_PREFIXES=[str(blocked_root)],
                ):
                    self.client.force_login(self.user)
                    response = self.client.post(
                        reverse("2server"),
                        {
                            "target_dir": str(target),
                            "files": SimpleUploadedFile("doc.pdf", b"%PDF-1", content_type="application/pdf"),
                        },
                        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                        HTTP_HOST="localhost",
                    )
                self.assertEqual(response.status_code, 400)
                payload = response.json()
                self.assertTrue(payload.get("errors") or payload.get("non_field_errors"))
            finally:
                blocked_root.chmod(0o755)

    def test_anonymous_redirected(self):
        response = self.client.get(reverse("2server"))
        self.assertEqual(response.status_code, 302)

    def test_authenticated_user_can_open_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("2server"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2server")

    def test_upload_saves_file_to_target_dir(self):
        with TemporaryDirectory() as tmp_dir:
            upload_root = Path(tmp_dir) / "incoming"
            upload_root.mkdir()
            storage_root = Path(tmp_dir) / "storage"
            storage_root.mkdir()
            with override_settings(
                HOMEHUB_STORAGE_ROOT=storage_root,
                HOMEHUB_DIRECT_UPLOAD_PATH_PREFIXES=[str(upload_root)],
            ):
                self.client.force_login(self.user)
                response = self.client.post(
                    reverse("2server"),
                    {
                        "target_dir": str(upload_root),
                        "files": SimpleUploadedFile("doc.pdf", b"%PDF-1", content_type="application/pdf"),
                    },
                )

            self.assertEqual(response.status_code, 302)
            saved = upload_root / "doc.pdf"
            self.assertTrue(saved.is_file())
            self.assertEqual(saved.read_bytes(), b"%PDF-1")
