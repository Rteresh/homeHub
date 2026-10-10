import logging
from uuid import NAMESPACE_URL, uuid5

from aiogram import F, Router
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.filters import Command
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.files import File
from django.db import close_old_connections, transaction

from apps.files.models import PrintJob
from apps.files.printing import PrintError, PrintService
from bot.services.telegram_download import (
    TelegramDownloadFailed, TelegramFileTooLarge, cleanup_temp,
    download_telegram_file, extract_media_payload, is_file_too_large_for_standard_api,
)

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("print"))
async def print_command(message, django_user, state):
    """Включает одноразовый режим печати для разрешённого пользователя в личном чате."""
    if message.chat.type != "private":
        await message.answer("Для печати отправьте /print в личный чат с ботом.")
        return
    try:
        await sync_to_async(PrintService.arm_telegram)(django_user, message.chat.id)
    except PrintError as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await message.answer(
        "Пришлите один документ или фото — отправлю на печать (A4, 1 копия).\n"
        "PDF, DOC, DOCX, ODT, JPG, PNG, TXT. Ожидаю 10 минут. /cancel — отмена.\n"
        "Из альбома напечатается только первый файл."
    )


@router.message(Command("cancel"))
async def cancel_command(message, django_user, state):
    """Отменяет ожидание документа, не отменяя уже переданное принтеру задание."""
    await sync_to_async(PrintService.cancel_telegram)(django_user, message.chat.id)
    await state.clear()
    await message.answer("Ожидание файла отменено. Уже отправленные задания остаются в очереди принтера.")


def claim_print(user, chat_id, message_id, original_name):
    """Резервирует попытку до скачивания и распознаёт повторный update после сброса режима."""
    request_id = uuid5(NAMESPACE_URL, f"homehub:telegram-print:{chat_id}:{message_id}")
    with transaction.atomic():
        existing = PrintJob.objects.filter(owner=user, request_id=request_id).first()
        if existing:
            return existing, False
        if not PrintService.consume_telegram(user, chat_id):
            # Конкурентный update мог дождаться блокировки уже после создания задания первым обработчиком.
            return PrintJob.objects.filter(owner=user, request_id=request_id).first(), False
        job, created = PrintJob.objects.get_or_create(
            owner=user, request_id=request_id, defaults={"original_name": original_name[:255]},
        )
        return job, created


def print_download(job, path, original_name):
    """Открывает скачанный файл в синхронном потоке и вызывает общий сервис сайта и бота."""
    close_old_connections()
    try:
        with path.open("rb") as source:
            return PrintService.process(job, File(source, name=original_name))
    finally:
        close_old_connections()


@router.message(F.document | F.photo)
async def receive_print(message, bot, django_user):
    """Забирает один документ для печати; обычные загрузки передаёт существующему роутеру медиатеки."""
    if message.chat.type != "private":
        return UNHANDLED
    payload = extract_media_payload(message)
    job, created = await sync_to_async(claim_print)(
        django_user, message.chat.id, message.message_id, payload.original_name,
    )
    if job is None:
        return UNHANDLED
    if not created:
        await message.answer(PrintService.result_message(job))
        return
    path = None
    progress = None
    try:
        if not settings.TELEGRAM_LOCAL_MODE and is_file_too_large_for_standard_api(payload.file_size):
            raise PrintError("Telegram позволяет скачать до 20 МБ. Загрузите файл через раздел «Печать» на сайте.")
        if payload.file_size is not None:
            PrintService.validate_upload(payload.original_name, payload.file_size)
        progress = await message.answer("Скачиваю и отправляю на печать…")
        path = await download_telegram_file(bot, payload.file_id, timeout=settings.TELEGRAM_DOWNLOAD_TIMEOUT)
        # Конвертация работает в отдельном потоке, чтобы остальные ORM-вызовы бота не ждали LibreOffice.
        job = await sync_to_async(print_download, thread_sensitive=False)(job, path, payload.original_name)
    except (PrintError, TelegramDownloadFailed, TelegramFileTooLarge) as exc:
        job.status, job.error = PrintJob.Status.FAILED, str(exc)[:500]
        await sync_to_async(job.save)(update_fields=["status", "error"])
    except Exception:
        logger.exception("Ошибка обработки Telegram-печати job_id=%s", job.pk)
        # При сбое ответа/БД не повторяем внешнюю печать: сохранённый результат важнее локальной ошибки.
        await sync_to_async(job.refresh_from_db)()
        if job.status == PrintJob.Status.PREPARING:
            job.status = PrintJob.Status.UNKNOWN
            job.error = "Запрос прервался. Проверьте очередь принтера перед повтором."
            await sync_to_async(job.save)(update_fields=["status", "error"])
    finally:
        await sync_to_async(cleanup_temp)(path)
    text = PrintService.result_message(job)
    if job.status == PrintJob.Status.FAILED:
        text += "\nДля нового файла отправьте /print ещё раз."
    if progress:
        await progress.edit_text(text)
    else:
        await message.answer(text)
