"""Очередь URL для краулера."""

import asyncio
from collections import defaultdict
from typing import Optional, List, Dict, Set
from urllib.parse import urlparse

from .logger import get_logger


class CrawlerQueue:
    """Асинхронная очередь URL с приоритетами."""
    
    def __init__(self, max_size: int = 0):
        """Инициализация очереди.
        
        Args:
            max_size: Максимальный размер очереди (0 = без ограничения)
        """
        self.max_size = max_size
        self.logger = get_logger(__name__)
        
        # Внутренние структуры
        self._pending: List[tuple] = []          # (приоритет, url, depth)
        self._visited: Set[str] = set()
        self._processing: Set[str] = set()
        self._failed: Dict[str, str] = {}
        self._queued: Set[str] = set()           # уже добавленные в pending
        
        # Синхронизация
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Event()
    
    async def add_url(self, url: str, priority: int = 0, depth: int = 0) -> bool:
        """Добавить URL в очередь.
        
        Args:
            url: URL для добавления
            priority: Приоритет (больше = раньше)
            depth: Глубина обхода
            
        Returns:
            bool: True если добавлен, False если уже был
        """
        async with self._lock:
            # Пропускаем дубликаты и уже посещённые
            if url in self._visited or url in self._processing or url in self._queued:
                return False
            
            if url in self._failed:
                return False
            
            if self.max_size > 0 and len(self._pending) >= self.max_size:
                self.logger.warning(f"Очередь переполнена, URL пропущен: {url}")
                return False
            
            self._pending.append((-priority, url, depth))
            self._queued.add(url)
            self._not_empty.set()
            return True
    
    async def get_next(self) -> Optional[tuple]:
        """Получить следующий URL.
        
        Returns:
            Optional[tuple]: (url, depth) или None, если очередь пуста
        """
        async with self._lock:
            if not self._pending:
                self._not_empty.clear()
                return None
            
            # Сортируем по приоритету (по убыванию), потом по времени добавления
            self._pending.sort(key=lambda x: (x[0],))
            
            _, url, depth = self._pending.pop(0)
            self._queued.discard(url)
            self._processing.add(url)
            return url, depth
    
    async def mark_processed(self, url: str) -> None:
        """Пометить URL как обработанный."""
        async with self._lock:
            self._processing.discard(url)
            self._visited.add(url)
    
    async def mark_failed(self, url: str, error: str) -> None:
        """Пометить URL как неудачный."""
        async with self._lock:
            self._processing.discard(url)
            self._failed[url] = error
            self._visited.add(url)
    
    async def is_visited(self, url: str) -> bool:
        """Проверить, посещён ли URL."""
        async with self._lock:
            return url in self._visited
    
    async def empty(self) -> bool:
        """Проверить, пуста ли очередь и нет ли активных задач."""
        async with self._lock:
            return not self._pending and not self._processing
    
    def get_stats(self) -> dict:
        """Получить статистику очереди."""
        return {
            "pending": len(self._pending),
            "processing": len(self._processing),
            "visited": len(self._visited),
            "failed": len(self._failed),
            "queued_total": len(self._queued),
        }
    
    @property
    def pending_count(self) -> int:
        return len(self._pending)
    
    @property
    def visited_count(self) -> int:
        return len(self._visited)
    
    @property
    def failed_count(self) -> int:
        return len(self._failed)
    
    def get_failed_urls(self) -> Dict[str, str]:
        """Получить словарь неудачных URL."""
        return dict(self._failed)
    
    def get_visited_urls(self) -> Set[str]:
        """Получить множество посещённых URL."""
        return set(self._visited)
    
    def clear(self) -> None:
        """Очистить очередь."""
        self._pending.clear()
        self._visited.clear()
        self._processing.clear()
        self._failed.clear()
        self._queued.clear()
        self._not_empty.clear()
    
    def __len__(self) -> int:
        return len(self._pending)
    
    def __bool__(self) -> bool:
        return bool(self._pending)


class DomainSemaphore:
    """Семафор для ограничения запросов к одному домену."""
    
    def __init__(self, max_per_domain: int = 2):
        self.max_per_domain = max_per_domain
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._lock = asyncio.Lock()
    
    async def acquire(self, url: str) -> asyncio.Semaphore:
        """Получить семафор для домена URL."""
        domain = self._get_domain(url)
        async with self._lock:
            if domain not in self._semaphores:
                self._semaphores[domain] = asyncio.Semaphore(self.max_per_domain)
            return self._semaphores[domain]
    
    def _get_domain(self, url: str) -> str:
        try:
            return urlparse(url).netloc or "unknown"
        except Exception:
            return "unknown"
    
    def get_stats(self) -> dict:
        return {
            "domains": len(self._semaphores),
            "max_per_domain": self.max_per_domain,
        }


class SemaphoreManager:
    """Менеджер семафоров: глобальный + по доменам."""
    
    def __init__(self, max_concurrent: int = 10, max_per_domain: int = 2):
        """Инициализация менеджера.
        
        Args:
            max_concurrent: Глобальное ограничение одновременных запросов
            max_per_domain: Ограничение запросов к одному домену
        """
        self.global_semaphore = asyncio.Semaphore(max_concurrent)
        self.domain_semaphores = DomainSemaphore(max_per_domain)
        self.max_concurrent = max_concurrent
        self.max_per_domain = max_per_domain
        
        # Счётчики активных задач
        self._active_count = 0
        self._lock = asyncio.Lock()
    
    async def acquire(self, url: str = None):
        """Получить глобальный семафор и семафор домена."""
        await self.global_semaphore.acquire()
        if url:
            domain_sem = await self.domain_semaphores.acquire(url)
            await domain_sem.acquire()
            return domain_sem
        
        return None
    
    async def release(self, url: str = None, domain_sem: asyncio.Semaphore = None):
        """Освободить семафоры."""
        if domain_sem is not None:
            domain_sem.release()
        self.global_semaphore.release()
    
    async def track_active(self, delta: int = 1) -> None:
        """Отслеживать количество активных задач."""
        async with self._lock:
            self._active_count += delta
    
    @property
    def active_count(self) -> int:
        return self._active_count
    
    def get_stats(self) -> dict:
        return {
            "max_concurrent": self.max_concurrent,
            "max_per_domain": self.max_per_domain,
            "active_tasks": self._active_count,
            "domains": self.domain_semaphores.get_stats()["domains"],
        }
    
    def __repr__(self) -> str:
        return (
            f"<SemaphoreManager(max_concurrent={self.max_concurrent}, "
            f"max_per_domain={self.max_per_domain})>"
        )