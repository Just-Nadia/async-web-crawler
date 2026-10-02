"""Стратегия повторов с экспоненциальным backoff."""

import asyncio
import random
import time
from typing import Callable, Any, Optional, Type, Tuple, List, Dict

from .logger import get_logger
from .config import RetryConfig
from .errors import (
    CrawlerError,
    TransientError,
    PermanentError,
    NetworkError,
)


class RetryStrategy:
    """Стратегия выполнения операций с повторами."""
    
    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        retry_on: Optional[List[Type[Exception]]] = None,
        no_retry_on: Optional[List[Type[Exception]]] = None,
        jitter: float = 0.1,
    ):
        """Инициализация стратегии.
        
        Args:
            max_retries: Максимальное число повторов
            backoff_factor: Множитель задержки
            initial_delay: Начальная задержка
            max_delay: Максимальная задержка
            retry_on: Типы исключений, при которых повторяем
            no_retry_on: Типы исключений, при которых НЕ повторяем
            jitter: Случайный разброс задержки (доля от текущей)
        """
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.jitter = jitter
        
        # По умолчанию повторяем только временные и сетевые ошибки
        self.retry_on = retry_on or [TransientError, NetworkError]
        # По умолчанию НЕ повторяем постоянные ошибки
        self.no_retry_on = no_retry_on or [PermanentError]
        
        self.logger = get_logger(__name__)
        
        # Статистика
        self._stats = {
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "retries": 0,
            "total_retry_time": 0.0,
            "by_type": {},
        }
    
    @classmethod
    def from_config(cls, config: RetryConfig) -> "RetryStrategy":
        """Создать стратегию из конфигурации."""
        return cls(
            max_retries=config.max_retries,
            backoff_factor=config.backoff_factor,
            initial_delay=config.initial_delay,
            max_delay=config.max_delay,
        )
    
    def _should_retry(self, exception: Exception) -> bool:
        """Определить, нужно ли повторять при данном исключении."""
        # Явный запрет имеет приоритет
        for exc_type in self.no_retry_on:
            if isinstance(exception, exc_type):
                return False
        
        # Разрешение на повтор
        for exc_type in self.retry_on:
            if isinstance(exception, exc_type):
                return True
        
        return False
    
    def _calculate_delay(self, attempt: int) -> float:
        """Рассчитать задержку перед следующей попыткой.
        
        Args:
            attempt: Номер попытки (0-based)
            
        Returns:
            float: Задержка в секундах
        """
        # Экспоненциальный backoff
        delay = self.initial_delay * (self.backoff_factor ** attempt)
        delay = min(delay, self.max_delay)
        
        # Jitter для избежания "thundering herd"
        if self.jitter > 0:
            jitter_amount = delay * self.jitter
            delay += random.uniform(0, jitter_amount)
        
        return delay
    
    async def execute_with_retry(
        self,
        coro_func: Callable[..., Any],
        *args,
        **kwargs
    ) -> Any:
        """Выполнить корутину с повторами при ошибках.
        
        Args:
            coro_func: Асинхронная функция
            *args, **kwargs: Аргументы для функции
            
        Returns:
            Результат выполнения
            
        Raises:
            Последнее исключение, если все попытки исчерпаны
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            self._stats["attempts"] += 1
            
            try:
                result = await coro_func(*args, **kwargs)
                self._stats["successes"] += 1
                
                if attempt > 0:
                    self.logger.info(
                        f"Успех после {attempt} повторов: "
                        f"{getattr(coro_func, '__name__', 'operation')}"
                    )
                
                return result
            
            except Exception as e:
                last_exception = e
                error_type = type(e).__name__
                self._stats["by_type"][error_type] = (
                    self._stats["by_type"].get(error_type, 0) + 1
                )
                
                # Определяем, повторять ли
                if not self._should_retry(e):
                    self._stats["failures"] += 1
                    self.logger.debug(
                        f"Ошибка {error_type} не подлежит повтору: {e}"
                    )
                    raise
                
                # Если это последняя попытка — выходим
                if attempt >= self.max_retries:
                    self._stats["failures"] += 1
                    self.logger.warning(
                        f"Все {self.max_retries + 1} попыток исчерпаны: {e}"
                    )
                    raise
                
                # Считаем задержку и ждём
                delay = self._calculate_delay(attempt)
                self._stats["retries"] += 1
                self._stats["total_retry_time"] += delay
                
                self.logger.info(
                    f"Попытка {attempt + 1}/{self.max_retries + 1} "
                    f"не удалась ({error_type}), повтор через {delay:.2f}с"
                )
                
                await asyncio.sleep(delay)
        
        # Сюда не должны попасть, но на всякий случай
        if last_exception:
            raise last_exception
    
    async def execute_with_retry_callback(
        self,
        coro_func: Callable[..., Any],
        on_retry: Optional[Callable[[int, Exception, float], None]] = None,
        *args,
        **kwargs
    ) -> Any:
        """Выполнить с повторами и callback'ом на каждый повтор.
        
        Args:
            coro_func: Асинхронная функция
            on_retry: Функция (attempt, exception, delay), вызываемая перед повтором
            *args, **kwargs: Аргументы для функции
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            self._stats["attempts"] += 1
            
            try:
                result = await coro_func(*args, **kwargs)
                self._stats["successes"] += 1
                return result
            
            except Exception as e:
                last_exception = e
                error_type = type(e).__name__
                self._stats["by_type"][error_type] = (
                    self._stats["by_type"].get(error_type, 0) + 1
                )
                
                if not self._should_retry(e):
                    self._stats["failures"] += 1
                    raise
                
                if attempt >= self.max_retries:
                    self._stats["failures"] += 1
                    raise
                
                delay = self._calculate_delay(attempt)
                self._stats["retries"] += 1
                self._stats["total_retry_time"] += delay
                
                if on_retry:
                    try:
                        result = on_retry(attempt + 1, e, delay)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as cb_err:
                        self.logger.warning(f"Ошибка в callback on_retry: {cb_err}")
                
                await asyncio.sleep(delay)
        
        if last_exception:
            raise last_exception
    
    def get_stats(self) -> dict:
        """Получить статистику."""
        stats = dict(self._stats)
        stats["avg_retry_time"] = (
            self._stats["total_retry_time"] / self._stats["retries"]
            if self._stats["retries"] > 0 else 0.0
        )
        return stats
    
    def reset_stats(self) -> None:
        """Сбросить статистику."""
        self._stats = {
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "retries": 0,
            "total_retry_time": 0.0,
            "by_type": {},
        }
    
    def __repr__(self) -> str:
        return (
            f"<RetryStrategy(max_retries={self.max_retries}, "
            f"backoff_factor={self.backoff_factor})>"
        )


class CircuitBreaker:
    """Простейший circuit breaker для защиты от нестабильных доменов."""
    
    STATE_CLOSED = "closed"       # Работает нормально
    STATE_OPEN = "open"           # Заблокирован
    STATE_HALF_OPEN = "half_open" # Пробуем восстановиться
    
    def __init__(
        self,
        failure_threshold: int = 5,
        success_threshold: int = 3,
        timeout: float = 30.0,
        half_open_max_calls: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.half_open_max_calls = half_open_max_calls
        
        # Состояние по доменам
        self._state: Dict[str, str] = {}
        self._failures: Dict[str, int] = {}
        self._successes: Dict[str, int] = {}
        self._opened_at: Dict[str, float] = {}
        self._half_open_calls: Dict[str, int] = {}
        
        self.logger = get_logger(__name__)
    
    def _domain_of(self, url: str) -> str:
        try:
            from urllib.parse import urlparse
            return urlparse(url).netloc or "unknown"
        except Exception:
            return "unknown"
    
    def is_available(self, url: str) -> bool:
        """Проверить, доступен ли домен."""
        domain = self._domain_of(url)
        state = self._state.get(domain, self.STATE_CLOSED)
        
        if state == self.STATE_CLOSED:
            return True
        
        if state == self.STATE_OPEN:
            # Проверяем, прошёл ли timeout
            opened_at = self._opened_at.get(domain, 0)
            if time.monotonic() - opened_at >= self.timeout:
                self._state[domain] = self.STATE_HALF_OPEN
                self._half_open_calls[domain] = 0
                self.logger.info(f"Circuit breaker: {domain} → half_open")
                return True
            return False
        
        if state == self.STATE_HALF_OPEN:
            calls = self._half_open_calls.get(domain, 0)
            if calls < self.half_open_max_calls:
                self._half_open_calls[domain] = calls + 1
                return True
            return False
        
        return True
    
    def record_success(self, url: str) -> None:
        """Записать успех."""
        domain = self._domain_of(url)
        state = self._state.get(domain, self.STATE_CLOSED)
        
        if state == self.STATE_HALF_OPEN:
            self._successes[domain] = self._successes.get(domain, 0) + 1
            if self._successes[domain] >= self.success_threshold:
                self._state[domain] = self.STATE_CLOSED
                self._failures[domain] = 0
                self._successes[domain] = 0
                self.logger.info(f"Circuit breaker: {domain} → closed")
        else:
            # Успех сбрасывает счётчик неудач
            self._failures[domain] = 0
    
    def record_failure(self, url: str) -> None:
        """Записать неудачу."""
        domain = self._domain_of(url)
        self._failures[domain] = self._failures.get(domain, 0) + 1
        
        state = self._state.get(domain, self.STATE_CLOSED)
        
        if state == self.STATE_HALF_OPEN:
            # В half_open любая ошибка возвращает в open
            self._state[domain] = self.STATE_OPEN
            self._opened_at[domain] = time.monotonic()
            self.logger.warning(f"Circuit breaker: {domain} → open (из half_open)")
        
        elif self._failures[domain] >= self.failure_threshold:
            self._state[domain] = self.STATE_OPEN
            self._opened_at[domain] = time.monotonic()
            self.logger.warning(
                f"Circuit breaker: {domain} → open "
                f"({self._failures[domain]} ошибок)"
            )
    
    def get_stats(self) -> dict:
        """Получить статистику."""
        return {
            "domains_tracked": len(self._state),
            "open": sum(1 for s in self._state.values() if s == self.STATE_OPEN),
            "half_open": sum(1 for s in self._state.values() if s == self.STATE_HALF_OPEN),
            "closed": sum(1 for s in self._state.values() if s == self.STATE_CLOSED),
        }
    
    def reset(self, url: Optional[str] = None) -> None:
        """Сбросить состояние (для всех доменов или одного)."""
        if url:
            domain = self._domain_of(url)
            self._state.pop(domain, None)
            self._failures.pop(domain, None)
            self._successes.pop(domain, None)
            self._opened_at.pop(domain, None)
            self._half_open_calls.pop(domain, None)
        else:
            self._state.clear()
            self._failures.clear()
            self._successes.clear()
            self._opened_at.clear()
            self._half_open_calls.clear()