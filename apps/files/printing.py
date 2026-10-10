import logging
import os
import re
import signal
import subprocess
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.files.models import PrintIntent, PrintJob

logger = logging.getLogger(__name__)
PRINT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".txt", ".doc", ".docx", ".odt"}
MAX_PRINT_BYTES = 50 * 1024 * 1024


class PrintError(Exception):
    """Сообщает пользователю о валидации или недоступности печати без внутренних путей и секретов."""


class PrintService:
    """Готовит приватный файл и передаёт его в CUPS хоста; очередь и драйвер остаются на сервере."""

    @staticmethod
    def validate_upload(name, size, copies=1):
        if Path(name).suffix.lower() not in PRINT_EXTENSIONS:
            raise PrintError("Поддерживаются PDF, DOC, DOCX, ODT, JPG, PNG и TXT.")
        if not size or size > MAX_PRINT_BYTES:
            raise PrintError("Файл должен быть непустым и не больше 50 МБ.")
        if not 1 <= copies <= 10:
            raise PrintError("Количество копий: от 1 до 10.")

    @staticmethod
    def _env():
        env = os.environ.copy()
        env.update(LC_ALL="C", LANG="C", CUPS_SERVER=settings.HOMEHUB_CUPS_SERVER)
        return env

    @classmethod
    def printer_status(cls):
        """Читает состояние настроенного принтера, не создавая задания печати."""
        if not settings.HOMEHUB_PRINTER:
            return "Принтер ещё не настроен."
        try:
            result = subprocess.run(
                ["lpstat", "-p", settings.HOMEHUB_PRINTER],
                env=cls._env(), capture_output=True, text=True, timeout=5, check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return "Принтер недоступен. Проверьте подключение и службу печати."
        return result.stdout.strip()

    @staticmethod
    def _validate_content(path):
        """Проверяет сигнатуры файлов; расширение и MIME от клиента сами по себе недостаточны."""
        extension = path.suffix
        with path.open("rb") as source:
            header = source.read(1024)
        valid = False
        if extension == ".pdf":
            valid = header.startswith(b"%PDF-")
        elif extension in {".jpg", ".jpeg"}:
            valid = header.startswith(b"\xff\xd8\xff")
        elif extension == ".png":
            valid = header.startswith(b"\x89PNG\r\n\x1a\n")
        elif extension == ".doc":
            valid = header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
        elif extension == ".txt":
            try:
                text = path.read_text(encoding="utf-8-sig")
                valid = not any(ord(char) < 32 and char not in "\n\r\t\f" for char in text)
            except UnicodeError:
                pass
        elif extension in {".docx", ".odt"}:
            try:
                with ZipFile(path) as archive:
                    # Ограничиваем распакованный размер офисного документа до запуска конвертера.
                    if sum(item.file_size for item in archive.infolist()) <= 200 * 1024 * 1024:
                        if extension == ".docx":
                            valid = {"[Content_Types].xml", "word/document.xml"} <= set(archive.namelist())
                        else:
                            valid = (
                                archive.getinfo("mimetype").file_size < 100
                                and archive.read("mimetype") == b"application/vnd.oasis.opendocument.text"
                            )
            except (BadZipFile, KeyError, RuntimeError):
                pass
        if not valid:
            raise PrintError("Содержимое файла не соответствует формату или файл повреждён. TXT должен быть в UTF-8.")

    @classmethod
    def _prepare(cls, path, workspace):
        cls._validate_content(path)
        if path.suffix not in {".doc", ".docx", ".odt"}:
            return path
        profile = workspace / "profile"
        try:
            with subprocess.Popen(
                ["libreoffice", f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore",
                 "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(workspace), str(path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            ) as process:
                try:
                    return_code = process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    # Завершаем всю группу конвертера, включая дочерний soffice.bin, до удаления каталога.
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    raise
                if return_code:
                    raise subprocess.CalledProcessError(return_code, "libreoffice")
        except (OSError, subprocess.SubprocessError) as exc:
            raise PrintError("Не удалось преобразовать документ в PDF. Попробуйте загрузить готовый PDF.") from exc
        pdf = path.with_suffix(".pdf")
        if not pdf.is_file() or not pdf.stat().st_size:
            raise PrintError("Документ не удалось открыть. Сохраните его в PDF и повторите загрузку.")
        cls._validate_content(pdf)
        return pdf

    @classmethod
    def submit(cls, *, user, upload, request_id, copies=1):
        """Создаёт ровно одну попытку печати для пользователя и request_id, очищает временный файл."""
        if not user.is_authenticated or not user.is_active:
            raise PermissionDenied
        existing = PrintJob.objects.filter(owner=user, request_id=request_id).first()
        if existing:
            return existing
        cls.validate_upload(upload.name, upload.size, copies)
        if not settings.HOMEHUB_PRINTER:
            raise PrintError("Принтер ещё не настроен.")
        job, created = PrintJob.objects.get_or_create(
            owner=user, request_id=request_id,
            defaults={"original_name": Path(upload.name).name[:255], "copies": copies},
        )
        if not created:
            return job
        return cls.process(job, upload)

    @classmethod
    def process(cls, job, upload):
        """Выполняет единственную зарезервированную попытку; вызывается только владельцем нового задания."""
        submitting = False
        try:
            cls.validate_upload(upload.name, upload.size, job.copies)
            if not settings.HOMEHUB_PRINTER:
                raise PrintError("Принтер ещё не настроен.")
            with TemporaryDirectory(prefix="homehub-print-") as directory:
                workspace = Path(directory)
                path = workspace / ("document" + Path(upload.name).suffix.lower())
                written = 0
                with path.open("wb") as destination:
                    for chunk in upload.chunks():
                        written += len(chunk)
                        if written > MAX_PRINT_BYTES:
                            raise PrintError("Файл больше 50 МБ.")
                        destination.write(chunk)
                cls.validate_upload(path.name, written, job.copies)
                printable = cls._prepare(path, workspace)
                submitting = True
                result = subprocess.run(
                    ["lp", "-d", settings.HOMEHUB_PRINTER, "-n", str(job.copies),
                     "-t", f"HomeHub-{job.pk}", "-o", "media=A4", "-o", "fit-to-page", "--", str(printable)],
                    env=cls._env(), capture_output=True, text=True, timeout=15, check=True,
                )
                match = re.search(r"request id is (\S+)", result.stdout)
                if match:
                    job.cups_job_id = match.group(1)[:255]
                    job.status = PrintJob.Status.SUBMITTED
                else:
                    job.status = PrintJob.Status.UNKNOWN
                    job.error = "Принтер принял запрос без номера задания. Проверьте очередь перед повтором."
        except PrintError as exc:
            job.status, job.error = PrintJob.Status.FAILED, str(exc)
        except FileNotFoundError:
            job.status = PrintJob.Status.FAILED
            job.error = "На сервере отсутствует клиент печати. Обратитесь к администратору."
        except subprocess.TimeoutExpired:
            job.status = PrintJob.Status.UNKNOWN
            job.error = "Служба печати не ответила вовремя. Проверьте очередь перед повтором."
        except subprocess.CalledProcessError:
            job.status = PrintJob.Status.UNKNOWN
            job.error = "Служба печати вернула ошибку. Проверьте принтер и очередь перед повтором."
        except Exception:
            logger.exception("Ошибка печати job_id=%s", job.pk)
            job.status = PrintJob.Status.UNKNOWN if submitting else PrintJob.Status.FAILED
            job.error = "Не удалось завершить запрос. Проверьте очередь принтера перед повтором."
        job.save(update_fields=["status", "cups_job_id", "error"])
        return job

    @staticmethod
    def result_message(job):
        if job.status == PrintJob.Status.SUBMITTED:
            return f"Передано на печать: {job.original_name}. Задание {job.cups_job_id}, копий: {job.copies}."
        return job.error or "Запрос уже обрабатывается. Повторная отправка на принтер заблокирована."

    @staticmethod
    def arm_telegram(user, chat_id):
        """Включает печать одного следующего файла на 10 минут; режим переживает перезапуск бота."""
        if not user.is_authenticated or not user.is_active:
            raise PermissionDenied
        if not settings.HOMEHUB_PRINTER:
            raise PrintError("Принтер ещё не настроен.")
        PrintIntent.objects.update_or_create(
            owner=user, chat_id=chat_id, defaults={"expires_at": timezone.now() + timedelta(minutes=10)},
        )

    @staticmethod
    def cancel_telegram(user, chat_id):
        PrintIntent.objects.filter(owner=user, chat_id=chat_id).delete()

    @staticmethod
    def consume_telegram(user, chat_id):
        """Атомарно забирает одно ожидание, чтобы несколько фото альбома не печатались одновременно."""
        with transaction.atomic():
            intent = PrintIntent.objects.select_for_update().filter(owner=user, chat_id=chat_id).first()
            if not intent:
                return False
            active = intent.expires_at > timezone.now()
            intent.delete()
            return active
