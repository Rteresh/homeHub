#!/usr/bin/env python
import os
import sys
from pathlib import Path


def ensure_supported_python() -> None:
    """Перенаправляет команды на Python из .venv, если системный интерпретатор слишком старый."""
    if sys.version_info >= (3, 10):
        return

    venv_python = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
    if venv_python.is_file():
        os.execv(str(venv_python), [str(venv_python), *sys.argv])

    print(
        "HomeHub требует Python 3.10 или новее. "
        "Создайте окружение: python3.12 -m venv .venv && source .venv/bin/activate",
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> None:
    """Запускает Django management commands для проекта HomeHub."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "homehub.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    ensure_supported_python()
    main()

