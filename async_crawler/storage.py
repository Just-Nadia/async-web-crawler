"""Асинхронное сохранение данных."""

import asyncio
import csv
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List, Optional

import aiofiles
import aiosqlite

from .logger import get_logger


class DataStorage(ABC):
    """Абстрактный базовый класс для хранилищ."""
    
    @abstractmethod
    async def save(self, data: Dict[str, Any]) -> None:
        """Сохранить одну запись."""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Закрыть ресурсы."""
        pass
    
    async def save_many(self, items: List[Dict[str, Any]]) -> None:
        """Сохранить несколько записей (по умолчанию — по одной)."""
        for item in items:
            await self.save(item)
    
    async def flush(self) -> None:
        """Сбросить буферы (опционально)."""
        pass


class JSONStorage(DataStorage):
    """Сохранение в JSON-файл (построчно, JSONL-подобно)."""
    
    def __init__(
        self,
        file_path: str = "crawler_results.json",
        indent: int = 2,
        ensure_ascii: bool = False,
        mode: str = "array",
    ):
        """Инициализация.
        
        Args:
            file_path: Путь к файлу
            indent: Отступ (для mode="array")
            ensure_ascii: Экранировать не-ASCII
            mode: "array" — один JSON-массив, "lines" — по строке на запись
        """
        self.file_path = Path(file_path)
        self.indent = indent
        self.ensure_ascii = ensure_ascii
        self.mode = mode
        self.logger = get_logger(__name__)
        
        self._items: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._initialized = False
    
    async def _ensure_init(self) -> None:
        if self._initialized:
            return
        
        async with self._lock:
            if self._initialized:
                return
            
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            
            if self.mode == "array":
                # Начинаем с пустого массива
                if not self.file_path.exists() or self.file_path.stat().st_size == 0:
                    async with aiofiles.open(self.file_path, "w", encoding="utf-8") as f:
                        await f.write("[]")
            else:
                # Для lines — просто пустой файл
                if not self.file_path.exists():
                    async with aiofiles.open(self.file_path, "w", encoding="utf-8"):
                        pass
            
            self._initialized = True
    
    async def save(self, data: Dict[str, Any]) -> None:
        await self._ensure_init()
        
        async with self._lock:
            if self.mode == "lines":
                # Одна запись = одна строка JSON
                line = json.dumps(data, ensure_ascii=self.ensure_ascii, default=str)
                async with aiofiles.open(self.file_path, "a", encoding="utf-8") as f:
                    await f.write(line + "\n")
            else:
                # array: перезаписываем весь файл (неэффективно для больших объёмов,
                # но даёт валидный JSON-массив)
                self._items.append(data)
                async with aiofiles.open(self.file_path, "w", encoding="utf-8") as f:
                    await f.write(
                        json.dumps(
                            self._items,
                            indent=self.indent,
                            ensure_ascii=self.ensure_ascii,
                            default=str,
                        )
                    )
    
    async def close(self) -> None:
        async with self._lock:
            self._items.clear()
        self._initialized = False


class CSVStorage(DataStorage):
    """Сохранение в CSV-файл."""
    
    # Поля, которые попадают в CSV. Списки/словари сериализуются в JSON-строки.
    DEFAULT_FIELDS = [
        "url", "status_code", "title", "text_length",
        "links_count", "images_count", "content_type",
        "crawled_at", "depth",
    ]
    
    def __init__(
        self,
        file_path: str = "crawler_results.csv",
        delimiter: str = ",",
        encoding: str = "utf-8",
        fields: Optional[List[str]] = None,
    ):
        self.file_path = Path(file_path)
        self.delimiter = delimiter
        self.encoding = encoding
        self.fields = fields or self.DEFAULT_FIELDS
        self.logger = get_logger(__name__)
        
        self._lock = asyncio.Lock()
        self._header_written = False
    
    def _prepare_row(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Подготовить строку: развернуть сложные поля."""
        row = {}
        for field in self.fields:
            value = data.get(field, "")
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            elif value is None:
                value = ""
            row[field] = value
        return row
    
    async def save(self, data: Dict[str, Any]) -> None:
        async with self._lock:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_exists = self.file_path.exists() and self.file_path.stat().st_size > 0
            
            async with aiofiles.open(
                self.file_path, "a", encoding=self.encoding, newline=""
            ) as f:
                row = self._prepare_row(data)
                writer = csv.DictWriter(
                    f, fieldnames=self.fields,
                    delimiter=self.delimiter,
                    extrasaction="ignore",
                )
                if not file_exists and not self._header_written:
                    # Заголовок пишем через прямой write, т.к. DictWriter пишет в sync-файл
                    header = self.delimiter.join(self.fields) + "\n"
                    await f.write(header)
                    self._header_written = True
                
                line = self.delimiter.join(
                    self._csv_escape(str(row.get(f, ""))) for f in self.fields
                ) + "\n"
                await f.write(line)
    
    @staticmethod
    def _csv_escape(value: str) -> str:
        """Экранировать значение для CSV."""
        if any(c in value for c in ('"', ',', '\n', '\r')):
            return '"' + value.replace('"', '""') + '"'
        return value
    
    async def close(self) -> None:
        pass


class SQLiteStorage(DataStorage):
    """Сохранение в SQLite через aiosqlite."""
    
    def __init__(
        self,
        db_path: str = "crawler.db",
        batch_size: int = 100,
        table_name: str = "pages",
    ):
        self.db_path = db_path
        self.batch_size = batch_size
        self.table_name = table_name
        self.logger = get_logger(__name__)
        
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
        self._buffer: List[Dict[str, Any]] = []
        self._initialized = False
    
    async def _ensure_init(self) -> None:
        if self._initialized:
            return
        
        async with self._lock:
            if self._initialized:
                return
            
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            
            self._conn = await aiosqlite.connect(self.db_path)
            
            await self._conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE,
                    status_code INTEGER,
                    title TEXT,
                    text TEXT,
                    links TEXT,
                    images TEXT,
                    metadata TEXT,
                    content_type TEXT,
                    content_length INTEGER,
                    depth INTEGER,
                    crawled_at TEXT,
                    fetch_time REAL,
                    parse_time REAL
                )
            """)
            await self._conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_url "
                f"ON {self.table_name}(url)"
            )
            await self._conn.commit()
            
            self._initialized = True
            self.logger.debug(f"SQLite инициализирован: {self.db_path}")
    
    async def save(self, data: Dict[str, Any]) -> None:
        await self._ensure_init()
        
        async with self._lock:
            self._buffer.append(data)
            if len(self._buffer) >= self.batch_size:
                await self._flush_unlocked()
    
    async def _flush_unlocked(self) -> None:
        """Сбросить буфер в БД (без захвата lock)."""
        if not self._buffer or self._conn is None:
            return
        
        rows = []
        for item in self._buffer:
            rows.append((
                item.get("url"),
                item.get("status_code", 0),
                item.get("title", ""),
                item.get("text", ""),
                json.dumps(item.get("links", []), ensure_ascii=False),
                json.dumps(item.get("images", []), ensure_ascii=False),
                json.dumps(item.get("metadata", {}), ensure_ascii=False),
                item.get("content_type", ""),
                item.get("content_length", 0),
                item.get("depth", 0),
                item.get("crawled_at", ""),
                item.get("fetch_time", 0.0),
                item.get("parse_time", 0.0),
            ))
        
        try:
            await self._conn.executemany(
                f"""
                INSERT OR REPLACE INTO {self.table_name}
                (url, status_code, title, text, links, images, metadata,
                 content_type, content_length, depth, crawled_at,
                 fetch_time, parse_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            await self._conn.commit()
        except Exception as e:
            self.logger.error(f"Ошибка записи в SQLite: {e}")
        finally:
            self._buffer.clear()
    
    async def flush(self) -> None:
        async with self._lock:
            await self._flush_unlocked()
    
    async def close(self) -> None:
        async with self._lock:
            await self._flush_unlocked()
            if self._conn:
                await self._conn.close()
                self._conn = None
            self._initialized = False


class MultiStorage(DataStorage):
    """Сохранение в несколько хранилищ одновременно."""
    
    def __init__(self, storages: List[DataStorage]):
        self.storages = storages
        self.logger = get_logger(__name__)
    
    async def save(self, data: Dict[str, Any]) -> None:
        # Параллельно во все хранилища
        await asyncio.gather(
            *(s.save(data) for s in self.storages),
            return_exceptions=True,
        )
    
    async def save_many(self, items: List[Dict[str, Any]]) -> None:
        await asyncio.gather(
            *(s.save_many(items) for s in self.storages),
            return_exceptions=True,
        )
    
    async def flush(self) -> None:
        await asyncio.gather(
            *(s.flush() for s in self.storages),
            return_exceptions=True,
        )
    
    async def close(self) -> None:
        await asyncio.gather(
            *(s.close() for s in self.storages),
            return_exceptions=True,
        )