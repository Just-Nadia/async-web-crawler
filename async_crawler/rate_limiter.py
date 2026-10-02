"""Ограничение скорости запросов."""

import asyncio
import random
import time
from typing import Dict, Optional
from urllib.parse import urlparse

from .logger import get_logger


class RateLimiter:
    """Ограничитель скорости запросов.
    
    Поддерживает глобальный лимит и отдельные лимиты по доменам.
    """
    
    def __init__(
        self,
        requests_per_second: float = 1.0,
        per_domain: bool = True,
        min_delay: float = 0.0,
        max_delay: float = 0.0,
        jitter: float = 0.0,
    ):
        """Инициализация.
        
        Args:
            requests_per_second: Лимит запросов в секунду
            per_domain: Отдельный лимит на каждый домен
            min_delay: Минимальная задержка между запросами
            max_delay: Максимальная задержка (для рандома)
            jitter: Случайный разброс задержки (0.0 - 1.0)
        """
        if requests_per_second <= 0:
            raise ValueError("requests_per_second должен быть > 0")
        
        self.requests_per_second = requests_per_second
        self.per_domain = per_domain
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.jitter = jitter
        
        # Минимальный интервал между запросами
        self._interval = 1.0 / requests_per_second
        
        # Последнее время запроса
        self._last_request: float = 0.0
        self._last_per_domain: Dict[str, float] = {}
        
        # Блокировки для каждого домена
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        
        self.logger = get_logger(__name__)
    
    def _get_domain(self, url: str) -> str:
        """Извлечь домен из URL."""
        try:
            return urlparse(url).netloc or "unknown"
        except Exception:
            return "unknown"
    
    def _calculate_delay(self) -> float:
        """Рассчитать дополнительную задержку."""
        delay = 0.0
        
        # Базовая задержка из min_delay
        if self.min_delay > 0:
            delay = self.min_delay
        
        # Случайная задержка до max_delay
        if self.max_delay > self.min_delay:
            delay = random.uniform(self.min_delay, self.max_delay)
        
        # Jitter — добавляем случайное отклонение
        if self.jitter > 0:
            jitter_amount = delay * self.jitter
            delay += random.uniform(0, jitter_amount)
        
        return delay
    
    async def acquire(self, url: Optional[str] = None) -> None:
        """Ожидать разрешения на запрос.
        
        Args:
            url: URL, к которому делается запрос (для per-domain лимита)
        """
        if self.per_domain and url:
            domain = self._get_domain(url)
            
            if domain not in self._locks:
                self._locks[domain] = asyncio.Lock()
            
            async with self._locks[domain]:
                await self._wait_for_domain(domain)
        else:
            async with self._global_lock:
                await self._wait_global()
    
    async def _wait_global(self) -> None:
        """Ожидание глобального лимита."""
        now = time.monotonic()
        elapsed = now - self._last_request
        
        if elapsed < self._interval:
            wait_time = self._interval - elapsed
            await asyncio.sleep(wait_time)
        
        # Добавляем случайную задержку, если настроено
        extra = self._calculate_delay()
        if extra > 0:
            await asyncio.sleep(extra)
        
        self._last_request = time.monotonic()
    
    async def _wait_for_domain(self, domain: str) -> None:
        """Ожидание лимита для конкретного домена."""
        now = time.monotonic()
        last = self._last_per_domain.get(domain, 0.0)
        elapsed = now - last
        
        if elapsed < self._interval:
            wait_time = self._interval - elapsed
            await asyncio.sleep(wait_time)
        
        extra = self._calculate_delay()
        if extra > 0:
            await asyncio.sleep(extra)
        
        self._last_per_domain[domain] = time.monotonic()
    
    def get_stats(self) -> dict:
        """Получить статистику."""
        return {
            "requests_per_second": self.requests_per_second,
            "interval": self._interval,
            "per_domain": self.per_domain,
            "domains_tracked": len(self._last_per_domain),
            "min_delay": self.min_delay,
            "max_delay": self.max_delay,
            "jitter": self.jitter,
        }
    
    def reset(self) -> None:
        """Сбросить состояние лимитера."""
        self._last_request = 0.0
        self._last_per_domain.clear()
        self._locks.clear()
    
    def __repr__(self) -> str:
        return (
            f"<RateLimiter(rps={self.requests_per_second}, "
            f"per_domain={self.per_domain})>"
        )