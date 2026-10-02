"""Парсинг sitemap.xml для получения URL."""

import asyncio
import xml.etree.ElementTree as ET
from typing import List, Optional, Set, Dict, Any
from urllib.parse import urljoin, urlparse

import aiohttp

from .logger import get_logger
from .errors import TransientError


class SitemapParser:
    """Парсер sitemap.xml."""
    
    def __init__(self, timeout: float = 30.0):
        """Инициализация парсера sitemap.
        
        Args:
            timeout: Таймаут загрузки sitemap
        """
        self.logger = get_logger(__name__)
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None
        
        # Кэш для уже обработанных sitemap
        self._processed_sitemaps: Set[str] = set()
        
        self.logger.info("SitemapParser инициализирован")
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получить сессию."""
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": "AsyncCrawler/1.0"},
            )
        return self._session
    
    async def close(self) -> None:
        """Закрыть сессию."""
        if self._session is not None:
            await self._session.close()
            self._session = None
    
    def _get_sitemap_url(self, base_url: str) -> str:
        """Получить URL sitemap для сайта."""
        domain = self._get_domain(base_url)
        return urljoin(domain, "/sitemap.xml")
    
    def _get_domain(self, url: str) -> str:
        """Извлечь домен из URL."""
        try:
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            return url.split("/")[2] if "//" in url else url
    
    async def fetch_sitemap(
        self,
        sitemap_url: str,
        max_urls: int = 10000
    ) -> List[str]:
        """Загрузить и распарсить sitemap.
        
        Args:
            sitemap_url: URL sitemap
            max_urls: Максимальное количество URL
            
        Returns:
            List[str]: Список URL из sitemap
        """
        if sitemap_url in self._processed_sitemaps:
            self.logger.debug(f"Sitemap уже обработан: {sitemap_url}")
            return []
        
        session = await self._get_session()
        urls = []
        
        try:
            self.logger.info(f"Загрузка sitemap: {sitemap_url}")
            
            async with session.get(sitemap_url) as response:
                if response.status != 200:
                    self.logger.warning(f"Ошибка загрузки sitemap: {response.status}")
                    return []
                
                content = await response.text()
                
                # Определяем тип sitemap
                if '<sitemapindex' in content:
                    # Индекс sitemap
                    self.logger.info(f"Обнаружен sitemap index: {sitemap_url}")
                    urls = await self._parse_sitemap_index(content, sitemap_url, max_urls)
                else:
                    # Обычная sitemap
                    urls = await self._parse_sitemap(content, sitemap_url, max_urls)
                
                self._processed_sitemaps.add(sitemap_url)
                self.logger.info(f"Извлечено {len(urls)} URL из sitemap")
                
                return urls
                
        except asyncio.TimeoutError:
            self.logger.warning(f"Таймаут загрузки sitemap: {sitemap_url}")
            
        except aiohttp.ClientError as e:
            self.logger.warning(f"Ошибка загрузки sitemap: {e}")
            
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка при загрузке sitemap: {e}")
        
        return []
    
    async def _parse_sitemap_index(
        self,
        content: str,
        base_url: str,
        max_urls: int
    ) -> List[str]:
        """Распарсить sitemap index."""
        urls = []
        
        try:
            root = ET.fromstring(content)
            
            # Пространство имен sitemap
            ns = {'sitemap': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            
            for sitemap in root.findall('sitemap:sitemap', ns):
                loc = sitemap.find('sitemap:loc', ns)
                if loc is not None and loc.text:
                    # Рекурсивно обрабатываем sitemap
                    sub_urls = await self.fetch_sitemap(loc.text, max_urls)
                    urls.extend(sub_urls)
                    
                    if len(urls) >= max_urls:
                        self.logger.info(f"Достигнут лимит URL: {max_urls}")
                        break
            
        except ET.ParseError as e:
            self.logger.warning(f"Ошибка парсинга sitemap index: {e}")
        
        return urls
    
    async def _parse_sitemap(
        self,
        content: str,
        base_url: str,
        max_urls: int
    ) -> List[str]:
        """Распарсить обычную sitemap."""
        urls = []
        
        try:
            root = ET.fromstring(content)
            
            # Пространство имен sitemap
            ns = {'sitemap': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            
            for url_elem in root.findall('sitemap:url', ns):
                loc = url_elem.find('sitemap:loc', ns)
                if loc is not None and loc.text:
                    # Проверяем URL
                    if loc.text.startswith(('http://', 'https://')):
                        urls.append(loc.text)
                        
                        if len(urls) >= max_urls:
                            self.logger.info(f"Достигнут лимит URL: {max_urls}")
                            break
            
        except ET.ParseError as e:
            self.logger.warning(f"Ошибка парсинга sitemap: {e}")
        
        return urls
    
    async def discover_sitemap(self, base_url: str) -> Optional[str]:
        """Обнаружить sitemap для сайта.
        
        Args:
            base_url: Базовый URL сайта
            
        Returns:
            Optional[str]: URL sitemap или None
        """
        domain = self._get_domain(base_url)
        
        # Пробуем стандартный путь
        sitemap_url = self._get_sitemap_url(base_url)
        
        session = await self._get_session()
        
        try:
            async with session.head(sitemap_url) as response:
                if response.status == 200:
                    return sitemap_url
        except Exception:
            pass
        
        # Пробуем другие варианты
        alternatives = [
            urljoin(domain, "/sitemap_index.xml"),
            urljoin(domain, "/sitemap1.xml"),
            urljoin(domain, "/sitemap.gz"),
        ]
        
        for alt_url in alternatives:
            try:
                async with session.head(alt_url) as response:
                    if response.status == 200:
                        return alt_url
            except Exception:
                continue
        
        return None


class SitemapUrlSource:
    """Источник URL из sitemap для краулера."""
    
    def __init__(self, parser: SitemapParser):
        self.parser = parser
        self.logger = get_logger(__name__)
        self._urls: List[str] = []
        self._index = 0
    
    async def fetch_urls(self, base_url: str, max_urls: int = 5000) -> List[str]:
        """Получить URL из sitemap."""
        # Пробуем обнаружить sitemap
        sitemap_url = await self.parser.discover_sitemap(base_url)
        
        if not sitemap_url:
            self.logger.warning(f"Sitemap не найден для {base_url}")
            return []
        
        urls = await self.parser.fetch_sitemap(sitemap_url, max_urls)
        
        self._urls = urls
        return urls
    
    def get_next_url(self) -> Optional[str]:
        """Получить следующий URL из списка."""
        if self._index < len(self._urls):
            url = self._urls[self._index]
            self._index += 1
            return url
        return None
    
    def reset(self) -> None:
        """Сбросить индекс."""
        self._index = 0