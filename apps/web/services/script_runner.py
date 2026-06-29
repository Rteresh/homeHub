from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.utils import timezone

# ponytail: только эти slug → scripts/*.sh, без произвольных команд
SCRIPT_SPECS: tuple[tuple[str, str, str, bool, bool], ...] = (
    ("backup-homehub", "backup_homehub.sh", "Полный бэкап (БД + config)", False, False),
    ("backup-db", "backup-db.sh", "Быстрый дамп PostgreSQL", False, False),
    ("export-storage", "export_storage.sh", "Выгрузка всего storage на носитель", True, True),
    ("export-backups", "export_backups.sh", "Выгрузка backups на носитель (--latest)", True, True),
)

RUN_TIMEOUT_SEC = int(os.environ.get("HOMEHUB_OPS_SCRIPT_TIMEOUT", "300"))


class ScriptRunnerError(Exception):
    """Ошибка валидации или запуска whitelisted ops-скрипта."""


@dataclass(frozen=True)
class ScriptInfo:
    slug: str
    filename: str
    label: str
    needs_target: bool
    supports_dry_run: bool
    description: str
    script_path: Path
    exists: bool


@dataclass
class ScriptRunResult:
    slug: str
    label: str
    command: str
    exit_code: int
    stdout: str
    stderr: str
    started_at: datetime
    duration_sec: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class ScriptRunnerService:
    """Запускает whitelisted bash-скрипты из scripts/; только для staff через ops UI."""

    @staticmethod
    def project_root() -> Path:
        return Path(settings.BASE_DIR).resolve()

    @staticmethod
    def scripts_dir() -> Path:
        return ScriptRunnerService.project_root() / "scripts"

    @staticmethod
    def ops_log_path() -> Path:
        path = Path(settings.HOMEHUB_STORAGE_ROOT) / "logs" / "ops-scripts.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def lock_path() -> Path:
        path = Path(settings.HOMEHUB_STORAGE_ROOT) / "tmp" / "ops-script.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def resolve_slug(cls, slug: str) -> ScriptInfo | None:
        for item_slug, filename, label, needs_target, supports_dry_run in SCRIPT_SPECS:
            if item_slug != slug:
                continue
            script_path = cls.scripts_dir() / filename
            return ScriptInfo(
                slug=item_slug,
                filename=filename,
                label=label,
                needs_target=needs_target,
                supports_dry_run=supports_dry_run,
                description=cls._description(item_slug),
                script_path=script_path,
                exists=script_path.is_file(),
            )
        return None

    @staticmethod
    def _description(slug: str) -> str:
        descriptions = {
            "backup-homehub": "Дамп БД и копия .env / docker-compose в storage/backup/YYYY-MM-DD/.",
            "backup-db": "Только PostgreSQL в storage/backup/db-dumps/.",
            "export-storage": "rsync storage → каталог на съёмном носителе (нужен mount в контейнере).",
            "export-backups": "rsync backup/ → backups/homehub/ДАТА/ на носителе.",
        }
        return descriptions.get(slug, "")

    @classmethod
    def list_scripts(cls) -> list[ScriptInfo]:
        return [info for slug, _, _, _, _ in SCRIPT_SPECS if (info := cls.resolve_slug(slug)) is not None]

    @classmethod
    def validate_export_target(cls, target_dir: str) -> Path:
        cleaned = target_dir.strip()
        if not cleaned:
            raise ScriptRunnerError("Укажите каталог носителя (например /media/usb).")
        if not cleaned.startswith("/"):
            raise ScriptRunnerError("Путь носителя должен быть абсолютным.")

        resolved = Path(cleaned).resolve()
        allowed_roots = [Path(prefix).resolve() for prefix in getattr(settings, "OPS_EXPORT_PATH_PREFIXES", ["/media", "/mnt"])]
        if not any(resolved == root or resolved.is_relative_to(root) for root in allowed_roots):
            allowed = ", ".join(str(root) for root in allowed_roots)
            raise ScriptRunnerError(f"Путь должен быть внутри одного из: {allowed}")

        if not resolved.is_dir():
            raise ScriptRunnerError(f"Каталог не найден: {resolved}")
        if not os.access(resolved, os.W_OK):
            raise ScriptRunnerError(f"Нет прав записи: {resolved}")
        return resolved

    @classmethod
    def run(
        cls,
        slug: str,
        *,
        target_dir: str = "",
        dry_run: bool = False,
        user: AbstractBaseUser | None = None,
    ) -> ScriptRunResult:
        info = cls.resolve_slug(slug)
        if info is None:
            raise ScriptRunnerError("Неизвестный скрипт.")
        if not info.exists:
            raise ScriptRunnerError(f"Файл скрипта не найден: {info.script_path}")
        if not os.access(info.script_path, os.X_OK):
            raise ScriptRunnerError(f"Скрипт не исполняемый: {info.script_path}")

        lock_path = cls.lock_path()
        if lock_path.exists():
            raise ScriptRunnerError("Уже выполняется другой скрипт. Подождите завершения.")

        command: list[str] = [str(info.script_path)]
        if dry_run and info.supports_dry_run:
            command.append("-n")
        if info.slug == "export-backups":
            command.append("--latest")
        if info.needs_target:
            command.append(str(cls.validate_export_target(target_dir)))

        env = os.environ.copy()
        env.setdefault("HOMEHUB_STORAGE_ROOT", str(settings.HOMEHUB_STORAGE_ROOT))
        env.setdefault("PROJECT_NAME", "homehub")

        started_at = timezone.now()
        lock_path.write_text(f"{slug}\n{started_at.isoformat()}\n", encoding="utf-8")
        timed_out = False
        stdout = ""
        stderr = ""
        exit_code = 1

        try:
            completed = subprocess.run(
                command,
                cwd=str(cls.project_root()),
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT_SEC,
                env=env,
                check=False,
            )
            exit_code = completed.returncode
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            stderr = f"{stderr}\nПревышен лимит времени ({RUN_TIMEOUT_SEC} с).".strip()
        finally:
            lock_path.unlink(missing_ok=True)

        duration_sec = (timezone.now() - started_at).total_seconds()
        result = ScriptRunResult(
            slug=info.slug,
            label=info.label,
            command=" ".join(command),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            started_at=started_at,
            duration_sec=duration_sec,
            timed_out=timed_out,
        )
        cls._append_ops_log(result, user=user)
        return result

    @classmethod
    def _append_ops_log(cls, result: ScriptRunResult, user: AbstractBaseUser | None) -> None:
        username = getattr(user, "username", "unknown")
        status = "OK" if result.ok else "FAIL"
        block = (
            f"\n{'=' * 60}\n"
            f"{result.started_at.isoformat()} user={username} script={result.slug} status={status}\n"
            f"cmd: {result.command}\n"
            f"exit={result.exit_code} duration={result.duration_sec:.1f}s timed_out={result.timed_out}\n"
            f"--- stdout ---\n{result.stdout[-8000:]}\n"
            f"--- stderr ---\n{result.stderr[-4000:]}\n"
        )
        with cls.ops_log_path().open("a", encoding="utf-8") as log_file:
            log_file.write(block)
