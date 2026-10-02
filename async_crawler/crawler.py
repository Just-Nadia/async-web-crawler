"""Асинхронный веб-краулер."""

import asyncio
import re
import time
from typing import List, Dict, Optional, Any, Set
from urllib.parse import urlparse, urljoin

import aiohttp

from .logger import get_logger
from .config import CrawlerConfig
from .models import PageData
from .errors import (
    CrawlerError,
    TransientError,
    PermanentError,
    NetworkError,
    RobotsBlockedError,
    CircuitBreakerOpenError,
    classify_http_error,
)
from .parser import HTMLParser
from .queue import CrawlerQueue, SemaphoreManager
from .rate_limiter import RateLimiter
from .robots import RobotsParser
from .retry import RetryStrategy, CircuitBreaker


class AsyncCrawler:
    """Асинхронный веб-краулер."""
    
    def __init__(
        self,
        max_concurrent: int = 10,
        max_depth: int = 3,
        max_pages: int = 100,
        requests_per_second: float = 1.0,
        respect_robots: bool = True,
        user_agent: str = "AsyncCrawler/1.0",
        config: Optional[CrawlerConfig] = None,
        storage: Optional[Any] = None,
    ):
        """Инициализация краулера.
        
        Args:
            max_concurrent: Максимум одновременных запросов
            max_depth: Максимальная глубина обхода
            max_pages: Максимум страниц
            requests_per_second: Лимит запросов в секунду
            respect_robots: Соблюдать robots.txt
            user_agent: User-Agent
            config: Конфигурация (если передана, перекрывает аргументы)
            storage: Хранилище для сохранения страниц
        """
        # Конфигурация
        self.config = config or CrawlerConfig(
            max_concurrent=max_concurrent,
            max_depth=max_depth,
            max_pages=max_pages,
            requests_per_second=requests_per_second,
            respect_robots=respect_robots,
            user_agent=user_agent,
        )
        
        self.logger = get_logger(__name__)
        self.storage = storage
        
        # Сессия создаётся лениво
        self._session: Optional[aiohttp.ClientSession] = None
        
        # Компоненты
        self.queue = CrawlerQueue()
        self.semaphores = SemaphoreManager(
            max_concurrent=self.config.max_concurrent,
            max_per_domain=2,
        )
        self.rate_limiter = RateLimiter(
            requests_per_second=self.config.requests_per_second,
            per_domain=True,
            min_delay=self.config.min_delay,
            max_delay=self.config.max_delay,
            jitter=self.config.jitter,
        )
        self.robots = RobotsParser(
            user_agent=self.config.robots_user_agent,
            cache_ttl=self.config.robots_cache_ttl,
        ) if self.config.respect_robots else None
        
        self.retry = RetryStrategy.from_config(self.config.retry)
        self.circuit_breaker = (
            CircuitBreaker(
                failure_threshold=self.config.circuit_breaker.failure_threshold,
                success_threshold=self.config.circuit_breaker.success_threshold,
                timeout=self.config.circuit_breaker.timeout,
                half_open_max_calls=self.config.circuit_breaker.half_open_max_calls,
            )
            if self.config.circuit_breaker.enabled else None
        )
        
        self.parser = HTMLParser(
            extract_links=self.config.extract_links,
            extract_text=self.config.extract_text,
            extract_metadata=self.config.extract_metadata,
        ) if self.config.parse_html else None
        
        # Результаты
        self.results: Dict[str, PageData] = {}
        self.error_results: Dict[str, Dict[str, str]] = {}
        
        # Скомпилированные фильтры URL
        self._exclude_re = [re.compile(p) for p in self.config.exclude_patterns]
        self._include_re = [re.compile(p) for p in self.config.include_patterns]
        
        # Статистика
        self._started_at: Optional[float] = None
        self._stats = {
            "pages_fetched": 0,
            "pages_parsed": 0,
            "errors": 0,
            "retries": 0,
            "blocked_by_robots": 0,
            "blocked_by_circuit": 0,
        }
        
        # Счётчики, читаемые advanced_crawler.py
        self.retries = 0
        self.blocked_by_robots = 0
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получить или создать HTTP-сессию."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(
                total=self.config.total_timeout,
                connect=self.config.connect_timeout,
                sock_read=self.config.read_timeout,
            )
            connector = aiohttp.TCPConnector(
                limit=self.config.max_concurrent * 2,
                limit_per_host=5,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={"User-Agent": self.config.user_agent},
            )
        return self._session
    
    async def close(self) -> None:
        """Закрыть все ресурсы."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        
        if self.robots:
            await self.robots.close()
        
        if self.storage and hasattr(self.storage, 'close'):
            try:
                await self.storage.close()
            except Exception as e:
                self.logger.warning(f"Ошибка закрытия storage: {e}")
        
        self.logger.info("Краулер закрыт")
    
    # ---------- Базовые методы загрузки ----------
    
    async def fetch_url(self, url: str) -> str:
        """Загрузить одну страницу.
        
        Args:
            url: URL страницы
            
        Returns:
            str: HTML-контент
            
        Raises:
            CrawlerError: При ошибке загрузки
        """
        session = await self._get_session()
        
        try:
            async with session.get(url, allow_redirects=True) as response:
                if response.status >= 400:
                    raise classify_http_error(response.status, url)
                
                content_type = response.headers.get("Content-Type", "")
                if "text/html" not in content_type and "application/xhtml" not in content_type:
                    raise PermanentError(
                        f"Неподдерживаемый Content-Type: {content_type}",
                        url,
                    )
                
                html = await response.text(errors="ignore")
                return html
        
        except aiohttp.ClientResponseError as e:
            raise classify_http_error(e.status, url)
        
        except asyncio.TimeoutError:
            raise TransientError("Таймаут запроса", url)
        
        except aiohttp.ClientConnectorError as e:
            raise NetworkError(f"Ошибка соединения: {e}", url)
        
        except aiohttp.ClientError as e:
            raise NetworkError(f"Сетевая ошибка: {e}", url)
        
        except CrawlerError:
            raise
        
        except Exception as e:
            raise CrawlerError(f"Неизвестная ошибка: {e}", url)
    
    async def fetch_urls(self, urls: List[str]) -> Dict[str, str]:
        """Параллельно загрузить список URL.
        
        Args:
            urls: Список URL
            
        Returns:
            Dict[str, str]: url -> html (только успешные)
        """
        async def safe_fetch(url: str) -> tuple:
            try:
                html = await self.fetch_url(url)
                return url, html
            except Exception as e:
                self.logger.warning(f"Ошибка загрузки {url}: {e}")
                return url, None
        
        tasks = [safe_fetch(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        
        return {url: html for url, html in results if html is not None}
    
    async def fetch_and_parse(self, url: str) -> Optional[PageData]:
        """Загрузить и распарсить страницу.
        
        Args:
            url: URL страницы
            
        Returns:
            PageData или None при ошибке
        """
        try:
            fetch_start = time.monotonic()
            html = await self.fetch_url(url)
            fetch_time = time.monotonic() - fetch_start
            
            if self.parser is None:
                # Без парсинга — только HTML
                return PageData(url=url, html=html, fetch_time=fetch_time, status_code=200)
            
            parse_start = time.monotonic()
            page = await self.parser.parse_html(html, url)
            page.parse_time = time.monotonic() - parse_start
            page.fetch_time = fetch_time
            page.status_code = 200
            
            return page
        
        except Exception:
            raise
    
    # ---------- Обработка одного URL с полным pipeline ----------
    
    async def _process_one(self, url: str, depth: int) -> Optional[PageData]:
        """Обработать один URL со всеми проверками и повторами."""
        # Проверка circuit breaker
        if self.circuit_breaker and not self.circuit_breaker.is_available(url):
            self._stats["blocked_by_circuit"] += 1
            raise CircuitBreakerOpenError(f"Домен временно недоступен", url)
        
        # Проверка robots.txt
        if self.robots:
            try:
                allowed = await self.robots.can_fetch(url)
                if not allowed:
                    self._stats["blocked_by_robots"] += 1
                    self.blocked_by_robots += 1
                    self.logger.info(f"robots.txt запрещает: {url}")
                    raise RobotsBlockedError(f"URL запрещён robots.txt", url)
            except RobotsBlockedError:
                raise
            except Exception as e:
                self.logger.warning(f"Ошибка проверки robots: {e}")
        
        # Rate limiting
        await self.rate_limiter.acquire(url)
        
        # Семафоры: глобальный + по домену
        domain_sem = await self.semaphores.acquire(url)
        
        async def do_fetch():
            return await self.fetch_and_parse(url)
        
        try:
            page = await self.retry.execute_with_retry(do_fetch)
            
            if self.circuit_breaker:
                self.circuit_breaker.record_success(url)
            
            self._stats["pages_fetched"] += 1
            if self.parser:
                self._stats["pages_parsed"] += 1
            
            self.retries = self.retry.get_stats()["retries"]
            
            return page
        
        except Exception as e:
            if self.circuit_breaker:
                self.circuit_breaker.record_failure(url)
            
            self._stats["errors"] += 1
            self.error_results[url] = {
                "error": str(e),
                "error_type": type(e).__name__,
            }
            raise
        
        finally:
            await self.semaphores.release(url, domain_sem)
    
    # ---------- Основной цикл краулинга ----------
    
    async def crawl(
        self,
        start_urls: List[str],
        max_pages: Optional[int] = None,
        max_depth: Optional[int] = None,
        same_domain_only: Optional[bool] = None,
        show_progress: bool = False,
    ) -> Dict[str, PageData]:
        """Запустить краулинг.
        
        Args:
            start_urls: Стартовые URL
            max_pages: Максимум страниц (перекрывает конфиг)
            max_depth: Максимальная глубина (перекрывает конфиг)
            same_domain_only: Только тот же домен
            show_progress: Показывать прогресс
            
        Returns:
            Dict[str, PageData]: url -> PageData
        """
        max_pages = max_pages if max_pages is not None else self.config.max_pages
        max_depth = max_depth if max_depth is not None else self.config.max_depth
        same_domain_only = (
            same_domain_only if same_domain_only is not None
            else self.config.same_domain_only
        )
        
        self._started_at = time.monotonic()
        self.results = {}
        self.error_results = {}
        
        # Домены стартовых URL (для фильтра same_domain_only)
        start_domains: Set[str] = set()
        for url in start_urls:
            start_domains.add(urlparse(url).netloc)
        
        # Добавляем стартовые URL в очередь
        for url in start_urls:
            await self.queue.add_url(url, priority=10, depth=0)
        
        self.logger.info(
            f"Старт краулинга: {len(start_urls)} URL, "
            f"max_pages={max_pages}, max_depth={max_depth}"
        )
        
        # Счётчик активных задач для отслеживания завершения
        active_tasks: Set[asyncio.Task] = set()
        
        progress_task = None
        if show_progress:
            progress_task = asyncio.create_task(self._progress_loop(max_pages))
        
        try:
            while True:
                # Проверяем лимит страниц
                if len(self.results) >= max_pages:
                    self.logger.info(f"Достигнут лимит страниц: {max_pages}")
                    break
                
                # Проверяем завершение: очередь пуста и нет активных задач
                if await self.queue.empty() and not active_tasks:
                    # Проверяем ещё раз — возможно, задачи добавили URL
                    await asyncio.sleep(0.05)
                    if await self.queue.empty() and not active_tasks:
                        break
                
                # Забираем URL из очереди
                result = await self.queue.get_next()
                
                if result is None:
                    # Очередь пуста, но активные задачи могут добавить URL
                    if active_tasks:
                        await asyncio.sleep(0.05)
                        continue
                    else:
                        break
                
                url, depth = result
                
                # Запускаем задачу
                task = asyncio.create_task(
                    self._crawl_one(url, depth, max_depth, same_domain_only, start_domains)
                )
                active_tasks.add(task)
                task.add_done_callback(active_tasks.discard)
        
        finally:
            if progress_task:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass
            
            # Ждём завершения оставшихся задач
            if active_tasks:
                await asyncio.gather(*active_tasks, return_exceptions=True)
        
        elapsed = time.monotonic() - self._started_at
        self.logger.info(
            f"Краулинг завершён: {len(self.results)} страниц, "
            f"{len(self.error_results)} ошибок, {elapsed:.2f}с"
        )
        
        return self.results
    
    async def _crawl_one(
        self,
        url: str,
        depth: int,
        max_depth: int,
        same_domain_only: bool,
        start_domains: Set[str],
    ) -> None:
        """Обработать одну страницу и добавить найденные ссылки в очередь."""
        try:
            page = await self._process_one(url, depth)
            
            if page is None:
                await self.queue.mark_processed(url)
                return
            
            # Сохраняем результат
            self.results[url] = page
            
            # Сохраняем в storage
            if self.storage:
                try:
                    await self.storage.save(page.to_dict())
                except Exception as e:
                    self.logger.warning(f"Ошибка сохранения {url}: {e}")
            
            await self.queue.mark_processed(url)
            
            # Добавляем найденные ссылки в очередь
            if depth < max_depth and page.links:
                for link in page.links:
                    if not self._is_url_allowed(link, url, same_domain_only, start_domains):
                        continue
                    await self.queue.add_url(link, priority=0, depth=depth + 1)
        
        except RobotsBlockedError:
            await self.queue.mark_failed(url, "Заблокирован robots.txt")
        
        except CircuitBreakerOpenError:
            await self.queue.mark_failed(url, "Circuit breaker открыт")
        
        except Exception as e:
            self.logger.debug(f"Ошибка обработки {url}: {e}")
            await self.queue.mark_failed(url, str(e))
    
    def _is_url_allowed(
        self,
        url: str,
        source_url: str,
        same_domain_only: bool,
        start_domains: Set[str],
    ) -> bool:
        """Проверить, разрешён ли URL для обхода."""
        try:
            parsed = urlparse(url)
            if not parsed.scheme in ("http", "https"):
                return False
            if not parsed.netloc:
                return False
        except Exception:
            return False
        
        # same_domain_only
        if same_domain_only:
            if parsed.netloc not in start_domains:
                return False
        
        # exclude_patterns
        for pattern in self._exclude_re:
            if pattern.search(url):
                return False
        
        # include_patterns (если заданы — URL должен подходить хотя бы под один)
        if self._include_re:
            if not any(p.search(url) for p in self._include_re):
                return False
        
        return True
    
    async def _progress_loop(self, max_pages: int) -> None:
        """Периодический вывод прогресса."""
        try:
            while True:
                await asyncio.sleep(self.config.progress_interval)
                done = len(self.results)
                stats = self.queue.get_stats()
                self.logger.info(
                    f"Прогресс: {done}/{max_pages} страниц, "
                    f"в очереди: {stats['pending']}, "
                    f"в работе: {stats['processing']}, "
                    f"ошибок: {len(self.error_results)}"
                )
        except asyncio.CancelledError:
            pass
    
    # ---------- Статистика и отчёты ----------
    
    def get_stats(self) -> dict:
        """Получить статистику краулера."""
        elapsed = 0.0
        if self._started_at:
            elapsed = time.monotonic() - self._started_at
        
        return {
            "pages_fetched": self._stats["pages_fetched"],
            "pages_parsed": self._stats["pages_parsed"],
            "errors": self._stats["errors"],
            "retries": self.retry.get_stats()["retries"],
            "blocked_by_robots": self._stats["blocked_by_robots"],
            "blocked_by_circuit": self._stats["blocked_by_circuit"],
            "elapsed_seconds": elapsed,
            "queue": self.queue.get_stats(),
            "semaphores": self.semaphores.get_stats(),
            "circuit_breaker": (
                self.circuit_breaker.get_stats() if self.circuit_breaker else {}
            ),
        }
    
    def get_error_report(self) -> str:
        """Текстовый отчёт об ошибках."""
        if not self.error_results:
            return "Ошибок нет"
        
        lines = [f"Ошибок: {len(self.error_results)}", ""]
        
        # Группируем по типу
        by_type: Dict[str, List[str]] = {}
        for url, info in self.error_results.items():
            by_type.setdefault(info.get("error_type", "unknown"), []).append(url)
        
        for err_type, urls in sorted(by_type.items(), key=lambda x: -len(x[1])):
            lines.append(f"{err_type}: {len(urls)}")
            for url in urls[:5]:
                lines.append(f"  - {url}")
            if len(urls) > 5:
                lines.append(f"  ... и ещё {len(urls) - 5}")
            lines.append("")
        
        return "\n".join(lines)
    
    def __repr__(self) -> str:
        return (
            f"<AsyncCrawler(pages={len(self.results)}, "
            f"errors={len(self.error_results)})>"
        )