"""Точка входа для запуска пакета как модуля: python -m async_crawler."""

import sys

from .cli import main


if __name__ == "__main__":
    sys.exit(main())