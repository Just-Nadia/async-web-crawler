"""Настройка логирования."""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional


_LOG_CONFIGURED = False
_DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    format_string: Optional[str] = None,
    date_format: Optional[str] = None,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
    force: bool = False,
) -> None:
    """Настроить логирование.
    
    Args:
        level: Уровень логирования (DEBUG/INFO/WARNING/ERROR/CRITICAL)
        log_file: Путь к файлу лога. Если None — только консоль.
        format_string: Формат сообщений
        date_format: Формат даты
        max_bytes: Максимальный размер файла до ротации
        backup_count: Сколько старых файлов хранить
        force: Переконфигурировать, даже если уже настроено
    """
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED and not force:
        return
    
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Убираем старые хендлеры при переконфигурации
    for h in root.handlers[:]:
        root.removeHandler(h)
    
    fmt = logging.Formatter(
        format_string or _DEFAULT_FORMAT,
        datefmt=date_format or _DEFAULT_DATEFMT,
    )
    
    # Консоль
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    root.addHandler(console)
    
    # Файл с ротацией
    if log_file:
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(fmt)
            root.addHandler(file_handler)
        except Exception as e:
            root.warning(f"Не удалось открыть лог-файл {log_file}: {e}")
    
    # Приглушаем слишком болтливые сторонние логгеры
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("charset_normalizer").setLevel(logging.WARNING)
    
    _LOG_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Получить логгер по имени модуля."""
    return logging.getLogger(name)