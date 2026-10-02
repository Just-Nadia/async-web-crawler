"""Парсинг и соблюдение robots.txt."""

import asyncio
import time
from typing import Dict, Optional, List
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

import aiohttp

from .logger import get_logger
from .errors import RobotsBlockedError


class RobotsParser:
    """Парсер robots.txt с кэшированием."""
    
    def __init__(
        self,
        user_agent: str = "*",
        cache_ttl: float = 3600.0,
        timeout: float = 10.0,
    ):
        """Инициализация.
        
        Args:
            user_agent: User-Agent для проверки правил
            cache_ttl: Время жизни кэша в секундах
            timeout: Таймаут загрузки robots.txt
        """
        self.user_agent = user_agent
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        
        # Кэш: domain -> (RobotFileParser, timestamp)
        self._cache: Dict[str, tuple] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        
        self.logger = get_logger(__name__)
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получить или создать сессию."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": self.user_agent},
            )
        return self._session
    
    async def close(self) -> None:
        """Закрыть сессию."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    def _get_domain(self, url: str) -> str:
        """Извлечь домен из URL."""
        try:
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            return ""
    
    def _get_robots_url(self, url: str) -> str:
        """Получить URL robots.txt для сайта."""
        domain = self._get_domain(url)
        return urljoin(domain, "/robots.txt") if domain else ""
    
    def _is_cache_valid(self, domain: str) -> bool:
        """Проверить, актуален ли кэш для домена."""
        if domain not in self._cache:
            return False
        
        _, timestamp = self._cache[domain]
        return (time.monotonic() - timestamp) < self.cache_ttl
    
    async def fetch_robots(self, base_url: str) -> Optional[RobotFileParser]:
        """Загрузить и распарсить robots.txt для сайта.
        
        Args:
            base_url: URL сайта
            
        Returns:
            RobotFileParser или None, если robots.txt недоступен
        """
        domain = self._get_domain(base_url)
        if not domain:
            return None
        
        # Проверяем кэш
        if self._is_cache_valid(domain):
            parser, _ = self._cache[domain]
            return parser
        
        # Блокировка на домен, чтобы не грузить robots.txt параллельно
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()
        
        async with self._locks[domain]:
            # Повторная проверка после получения блокировки
            if self._is_cache_valid(domain):
                parser, _ = self._cache[domain]
                return parser
            
            parser = await self._download_robots(base_url)
            self._cache[domain] = (parser, time.monotonic())
            return parser
    
    async def _download_robots(self, base_url: str) -> Optional[RobotFileParser]:
        """Скачать и распарсить robots.txt."""
        robots_url = self._get_robots_url(base_url)
        if not robots_url:
            return None
        
        parser = RobotFileParser()
        parser.set_url(robots_url)
        
        try:
            session = await self._get_session()
            async with session.get(robots_url) as response:
                if response.status == 200:
                    content = await response.text()
                    parser.parse(content.splitlines())
                    self.logger.debug(f"robots.txt загружен: {robots_url}")
                    return parser
                
                elif response.status == 404:
                    # robots.txt отсутствует — всё разрешено
                    self.logger.debug(f"robots.txt не найден: {robots_url}")
                    parser.parse([])  # Пустые правила = всё разрешено
                    return parser
                
                else:
                    self.logger.warning(
                        f"robots.txt вернул {response.status}: {robots_url}"
                    )
                    # При ошибке — разрешаем всё, но логируем
                    parser.parse([])
                    return parser
        
        except asyncio.TimeoutError:
            self.logger.warning(f"Таймаут загрузки robots.txt: {robots_url}")
            parser.parse([])
            return parser
        
        except aiohttp.ClientError as e:
            self.logger.warning(f"Ошибка загрузки robots.txt: {e}")
            parser.parse([])
            return parser
        
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка robots.txt: {e}")
            return None
    
    async def can_fetch(self, url: str, user_agent: Optional[str] = None) -> bool:
        """Проверить, разрешён ли URL для данного User-Agent.
        
        Args:
            url: Проверяемый URL
            user_agent: User-Agent (по умолчанию self.user_agent)
            
        Returns:
            bool: True если URL разрешён
        """
        ua = user_agent or self.user_agent
        
        parser = await self.fetch_robots(url)
        if parser is None:
            # Не смогли получить robots — разрешаем
            return True
        
        try:
            return parser.can_fetch(ua, url)
        except Exception as e:
            self.logger.warning(f"Ошибка проверки can_fetch: {e}")
            return True
    
    async def get_crawl_delay(self, url: str, user_agent: Optional[str] = None) -> Optional[float]:
        """Получить Crawl-delay из robots.txt.
        
        Args:
            url: URL сайта
            user_agent: User-Agent
            
        Returns:
            Optional[float]: Задержка в секундах или None
        """
        ua = user_agent or self.user_agent
        
        parser = await self.fetch_robots(url)
        if parser is None:
            return None
        
        try:
            delay = parser.crawl_delay(ua)
            return float(delay) if delay is not None else None
        except Exception:
            return None
    
    async def check_url(self, url: str) -> None:
        """Проверить URL и бросить исключение, если запрещён.
        
        Raises:
            RobotsBlockedError: Если URL запрещён
        """
        if not await self.can_fetch(url):
            raise RobotsBlockedError(f"URL запрещён robots.txt", url)
    
    def get_stats(self) -> dict:
        """Получить статистику."""
        return {
            "user_agent": self.user_agent,
            "cached_domains": len(self._cache),
            "cache_ttl": self.cache_ttl,
        }
    
    def clear_cache(self) -> None:
        """Очистить кэш robots.txt."""
        self._cache.clear()
        self._locks.clear()