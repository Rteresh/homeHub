import subprocess
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4
from zipfile import ZipFile

from aiogram.dispatcher.event.bases import UNHANDLED
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.files.models import PrintIntent, PrintJob
from apps.files.printing import PrintError, PrintService
from bot.routers.printing import claim_print, print_command, receive_print, cancel_command
from bot.services.telegram_download import MediaPayload


@override_settings(HOMEHUB_PRINTER="SCX-3400", HOMEHUB_CUPS_SERVER="/run/cups/cups.sock")
class PrintingTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="printer")
        self.other = get_user_model().objects.create_user(username="other")
        self.client.force_login(self.user)

    def pdf(self):
        return SimpleUploadedFile("document.pdf", b"%PDF-1.4\nexample", content_type="application/pdf")

    @patch("apps.files.printing.subprocess.run")
    def test_submit_copies_socket_cleanup_and_duplicate(self, run):
        paths = []

        def accept(command, **kwargs):
            paths.append(Path(command[-1]))
            self.assertTrue(paths[-1].is_file())
            self.assertEqual(kwargs["env"]["CUPS_SERVER"], "/run/cups/cups.sock")
            self.assertEqual(command[command.index("-n") + 1], "2")
            self.assertNotIn("shell", kwargs)
            return subprocess.CompletedProcess(command, 0, "request id is SCX-3400-42 (1 file(s))\n", "")

        run.side_effect = accept
        request_id = uuid4()
        first = PrintService.submit(user=self.user, upload=self.pdf(), request_id=request_id, copies=2)
        second = PrintService.submit(user=self.user, upload=self.pdf(), request_id=request_id, copies=2)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.cups_job_id, "SCX-3400-42")
        self.assertEqual(first.status, PrintJob.Status.SUBMITTED)
        self.assertEqual(run.call_count, 1)
        self.assertFalse(paths[0].parent.exists())

    @patch("apps.files.printing.subprocess.run")
    def test_timeout_never_retries_request(self, run):
        run.side_effect = subprocess.TimeoutExpired("lp", 15)
        request_id = uuid4()
        job = PrintService.submit(user=self.user, upload=self.pdf(), request_id=request_id)
        self.assertEqual(job.status, PrintJob.Status.UNKNOWN)
        PrintService.submit(user=self.user, upload=self.pdf(), request_id=request_id)
        self.assertEqual(run.call_count, 1)

    @patch("apps.files.printing.subprocess.run")
    def test_cups_failure_does_not_claim_success(self, run):
        run.side_effect = subprocess.CalledProcessError(1, "lp", stderr="not available")
        job = PrintService.submit(user=self.user, upload=self.pdf(), request_id=uuid4())
        self.assertEqual(job.status, PrintJob.Status.UNKNOWN)
        self.assertEqual(job.cups_job_id, "")

    @patch("apps.files.printing.subprocess.run")
    def test_disguised_pdf_not_sent(self, run):
        job = PrintService.submit(
            user=self.user, upload=SimpleUploadedFile("fake.pdf", b"not a pdf"), request_id=uuid4(),
        )
        self.assertEqual(job.status, PrintJob.Status.FAILED)
        run.assert_not_called()

    def test_format_empty_size_and_copies_rejected(self):
        for name, size, copies in [("run.sh", 3, 1), ("file.pdf", 0, 1), ("file.pdf", 51 * 1024**2, 1), ("file.pdf", 5, 11)]:
            with self.subTest(name=name, size=size, copies=copies), self.assertRaises(PrintError):
                PrintService.validate_upload(name, size, copies)

    @patch("apps.files.printing.subprocess.Popen")
    @patch("apps.files.printing.subprocess.run")
    def test_office_converted_with_private_profile(self, run, popen):
        archive = BytesIO()
        with ZipFile(archive, "w") as docx:
            docx.writestr("[Content_Types].xml", "<Types/>")
            docx.writestr("word/document.xml", "<document/>")

        def convert(command, **kwargs):
            self.assertTrue(command[1].startswith("-env:UserInstallation=file:///"))
            self.assertTrue(kwargs["start_new_session"])
            Path(command[-1]).with_suffix(".pdf").write_bytes(b"%PDF-1.4\nconverted")
            process = Mock()
            process.wait.return_value = 0
            context = Mock()
            context.__enter__ = Mock(return_value=process)
            context.__exit__ = Mock(return_value=False)
            return context

        def execute(command, **kwargs):
            self.assertTrue(command[-1].endswith(".pdf"))
            return subprocess.CompletedProcess(command, 0, "request id is SCX-3400-43 (1 file(s))", "")

        popen.side_effect = convert
        run.side_effect = execute
        job = PrintService.submit(
            user=self.user, upload=SimpleUploadedFile("letter.docx", archive.getvalue()), request_id=uuid4(),
        )
        self.assertEqual(job.status, PrintJob.Status.SUBMITTED)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(popen.call_count, 1)

    @patch("apps.files.printing.subprocess.Popen")
    @patch("apps.files.printing.subprocess.run")
    def test_converter_no_output_does_not_print(self, run, popen):
        popen.return_value.__enter__.return_value.wait.return_value = 0
        upload = SimpleUploadedFile("legacy.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1data")
        job = PrintService.submit(user=self.user, upload=upload, request_id=uuid4())
        self.assertEqual(job.status, PrintJob.Status.FAILED)
        run.assert_not_called()

    @patch("apps.files.printing.os.killpg")
    @patch("apps.files.printing.subprocess.Popen")
    @patch("apps.files.printing.subprocess.run")
    def test_converter_timeout_kills_children_without_printing(self, run, popen, killpg):
        process = popen.return_value.__enter__.return_value
        process.pid = 1234
        process.wait.side_effect = [subprocess.TimeoutExpired("libreoffice", 60), 0]
        job = PrintService.submit(
            user=self.user, upload=SimpleUploadedFile("legacy.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1data"),
            request_id=uuid4(),
        )
        self.assertEqual(job.status, PrintJob.Status.FAILED)
        killpg.assert_called_once()
        run.assert_not_called()

    def test_access_and_csrf(self):
        anonymous = Client()
        self.assertEqual(anonymous.get(reverse("print-document")).status_code, 302)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(reverse("print-document"), {"request_id": uuid4(), "document": self.pdf(), "copies": 1})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PrintJob.objects.exists())

    @patch("apps.files.printing.subprocess.run")
    def test_web_upload_redirect_and_private_history(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "request id is SCX-3400-44 (1 file(s))", "")
        PrintJob.objects.create(owner=self.other, original_name="private-other.pdf")
        request_id = uuid4()
        for attempt in range(2):
            response = self.client.post(reverse("print-document"), {"request_id": request_id, "document": self.pdf(), "copies": 1})
            self.assertRedirects(response, reverse("print-document"), fetch_redirect_response=False)
        self.assertEqual(run.call_count, 1)
        response = self.client.get(reverse("print-document"))
        self.assertContains(response, "document.pdf")
        self.assertNotContains(response, "private-other.pdf")

    def test_intent_is_one_shot_scoped_and_durable(self):
        PrintService.arm_telegram(self.user, 123)
        self.assertEqual(claim_print(self.other, 123, 1, "other.pdf"), (None, False))
        self.assertEqual(claim_print(self.user, 456, 1, "other-chat.pdf"), (None, False))
        job, created = claim_print(self.user, 123, 1, "first.pdf")
        self.assertTrue(created)
        self.assertFalse(PrintIntent.objects.exists())
        duplicate, created = claim_print(self.user, 123, 1, "first.pdf")
        self.assertEqual(duplicate.pk, job.pk)
        self.assertFalse(created)
        self.assertEqual(claim_print(self.user, 123, 2, "second.pdf"), (None, False))

    def test_expired_and_cancelled_intent(self):
        PrintService.arm_telegram(self.user, 123)
        PrintIntent.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertFalse(PrintService.consume_telegram(self.user, 123))
        PrintService.arm_telegram(self.user, 123)
        PrintService.cancel_telegram(self.user, 123)
        self.assertFalse(PrintService.consume_telegram(self.user, 123))

    def message(self):
        message = Mock()
        message.chat.id, message.chat.type, message.message_id = 123, "private", 77
        message.answer = AsyncMock()
        message.answer.return_value.edit_text = AsyncMock()
        return message

    def test_print_and_cancel_commands(self):
        message, state = self.message(), AsyncMock()
        async_to_sync(print_command)(message, self.user, state)
        self.assertTrue(PrintIntent.objects.filter(owner=self.user, chat_id=123).exists())
        async_to_sync(cancel_command)(message, self.user, state)
        self.assertFalse(PrintIntent.objects.exists())

    @patch("bot.routers.printing.extract_media_payload")
    @patch("bot.routers.printing.download_telegram_file", new_callable=AsyncMock)
    @patch("apps.files.printing.subprocess.run")
    def test_telegram_file_printed_once_and_temp_removed(self, run, download, extract):
        message = self.message()
        extract.return_value = MediaPayload("file-id", "photo.jpg", "image/jpeg", 7)
        run.return_value = subprocess.CompletedProcess([], 0, "request id is SCX-3400-45 (1 file(s))", "")
        PrintService.arm_telegram(self.user, 123)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "telegram.bin"
            path.write_bytes(b"\xff\xd8\xffdata")
            download.return_value = path
            async_to_sync(receive_print)(message, Mock(), self.user)
            self.assertFalse(path.exists())
            async_to_sync(receive_print)(message, Mock(), self.user)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(download.await_count, 1)
        self.assertEqual(PrintJob.objects.get().status, PrintJob.Status.SUBMITTED)

    @patch("bot.routers.printing.extract_media_payload")
    @patch("bot.routers.printing.download_telegram_file", new_callable=AsyncMock)
    def test_normal_media_passes_through_and_large_print_fails(self, download, extract):
        message = self.message()
        extract.return_value = MediaPayload("file-id", "large.pdf", "application/pdf", 21 * 1024**2)
        self.assertIs(async_to_sync(receive_print)(message, Mock(), self.user), UNHANDLED)
        PrintService.arm_telegram(self.user, 123)
        with override_settings(TELEGRAM_LOCAL_MODE=False):
            async_to_sync(receive_print)(message, Mock(), self.user)
        download.assert_not_awaited()
        self.assertEqual(PrintJob.objects.get().status, PrintJob.Status.FAILED)

    def test_group_command_does_not_arm(self):
        message = self.message()
        message.chat.type = "group"
        async_to_sync(print_command)(message, self.user, AsyncMock())
        self.assertFalse(PrintIntent.objects.exists())
