import asyncio
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


async def schedule_server_shutdown() -> None:
    """Откладывает выключение сервера, чтобы Telegram успел доставить ответ пользователю."""
    command = (settings.HOMEHUB_SHUTDOWN_COMMAND or "").strip()
    if not command:
        logger.error("HOMEHUB_SHUTDOWN_COMMAND не задан — выключение сервера отменено.")
        return

    await asyncio.sleep(1)
    logger.warning("Запуск команды выключения сервера: %s", command)
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(
            "Команда выключения завершилась с кодом %s: %s",
            proc.returncode,
            stderr.decode(errors="replace").strip(),
        )
