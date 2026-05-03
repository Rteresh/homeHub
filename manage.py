#!/usr/bin/env python
import os
import sys


def main() -> None:
    """Запускает Django management commands для проекта HomeHub."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "homehub.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

