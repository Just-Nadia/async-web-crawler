"""Парсинг HTML и извлечение структурированных данных."""

import asyncio
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .logger import get_logger
from .errors import ParseError
from .models import PageData


class HTMLParser:
    """Парсер HTML с извлечением структурированных данных."""
    
    DEFAULT_TEXT_SELECTORS = ["main", "article", "div.content", "body"]
    
    def __init__(
        self,
        parser: str = "lxml",
        extract_links: bool = True,
        extract_text: bool = True,
        extract_metadata: bool = True,
    ):
        """Инициализация парсера.
        
        Args:
            parser: Бэкенд BeautifulSoup (lxml, html.parser)
            extract_links: Извлекать ссылки
            extract_text: Извлекать текст
            extract_metadata: Извлекать метаданные
        """
        self.parser_name = parser
        self.extract_links_flag = extract_links
        self.extract_text_flag = extract_text
        self.extract_metadata_flag = extract_metadata
        self.logger = get_logger(__name__)
    
    def _get_soup(self, html: str) -> BeautifulSoup:
        """Создать объект BeautifulSoup с fallback."""
        try:
            return BeautifulSoup(html, self.parser_name)
        except Exception:
            # Fallback на встроенный парсер, если lxml недоступен
            try:
                return BeautifulSoup(html, "html.parser")
            except Exception as e:
                raise ParseError(f"Не удалось создать soup: {e}")
    
    async def parse_html(self, html: str, url: str = "") -> PageData:
        """Асинхронный парсинг HTML.
        
        Args:
            html: HTML-контент
            url: URL страницы (для конвертации относительных ссылок)
            
        Returns:
            PageData: Извлечённые данные
        """
        if not html:
            raise ParseError("Пустой HTML", url)
        
        # Парсинг CPU-bound — уводим в поток, чтобы не блокировать loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._parse_sync, html, url)
    
    def _parse_sync(self, html: str, url: str) -> PageData:
        """Синхронный парсинг (выполняется в executor)."""
        soup = self._get_soup(html)
        
        page = PageData(url=url, html=html)
        
        if self.extract_metadata_flag:
            meta = self.extract_metadata(soup)
            page.title = meta.get("title", "")
            page.metadata = meta
        
        if self.extract_text_flag:
            page.text = self.extract_text(soup)
        
        if self.extract_links_flag:
            page.links = self.extract_links(soup, url)
        
        page.images = self.extract_images(soup, url)
        page.headers = self.extract_headers(soup)
        
        return page
    
    def extract_links(self, soup: BeautifulSoup, base_url: str = "") -> List[str]:
        """Извлечь все ссылки и преобразовать в абсолютные URL."""
        links = []
        seen = set()
        
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            
            # Пропускаем служебные ссылки
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            
            # Конвертируем в абсолютный URL
            absolute = self._to_absolute(href, base_url)
            if not absolute:
                continue
            
            # Валидируем
            if not self._is_valid_url(absolute):
                continue
            
            # Убираем дубликаты, сохраняя порядок
            if absolute in seen:
                continue
            seen.add(absolute)
            links.append(absolute)
        
        return links
    
    def extract_text(self, soup: BeautifulSoup, selector: Optional[str] = None) -> str:
        """Извлечь основной текст страницы."""
        try:
            if selector:
                node = soup.select_one(selector)
                target = node if node else soup
            else:
                # Пробуем найти основной контент
                target = None
                for sel in self.DEFAULT_TEXT_SELECTORS:
                    node = soup.select_one(sel)
                    if node:
                        target = node
                        break
                if target is None:
                    target = soup
            
            # Удаляем скрипты и стили
            for tag in target(["script", "style", "noscript", "template"]):
                tag.decompose()
            
            text = target.get_text(separator=" ", strip=True)
            # Схлопываем множественные пробелы
            text = " ".join(text.split())
            return text
        except Exception as e:
            self.logger.warning(f"Ошибка извлечения текста: {e}")
            return ""
    
    def extract_metadata(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Извлечь метаданные: title, description, keywords, og:*."""
        meta: Dict[str, Any] = {}
        
        try:
            if soup.title and soup.title.string:
                meta["title"] = soup.title.string.strip()
            
            for name in ("description", "keywords", "author", "robots"):
                tag = soup.find("meta", attrs={"name": name})
                if tag and tag.get("content"):
                    meta[name] = tag["content"].strip()
            
            # Open Graph
            for og in soup.find_all("meta", attrs={"property": True}):
                prop = og.get("property", "")
                if prop.startswith("og:") and og.get("content"):
                    meta[prop] = og["content"].strip()
            
            # Язык
            if soup.html and soup.html.get("lang"):
                meta["lang"] = soup.html["lang"]
            
            # Canonical
            canonical = soup.find("link", attrs={"rel": "canonical"})
            if canonical and canonical.get("href"):
                meta["canonical"] = canonical["href"]
        
        except Exception as e:
            self.logger.warning(f"Ошибка извлечения метаданных: {e}")
        
        return meta
    
    def extract_images(self, soup: BeautifulSoup, base_url: str = "") -> List[Dict[str, str]]:
        """Извлечь изображения с src и alt."""
        images = []
        seen = set()
        
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if not src:
                continue
            
            absolute = self._to_absolute(src.strip(), base_url)
            if not absolute or absolute in seen:
                continue
            seen.add(absolute)
            
            images.append({
                "src": absolute,
                "alt": (img.get("alt") or "").strip(),
            })
        
        return images
    
    def extract_headers(self, soup: BeautifulSoup) -> List[str]:
        """Извлечь заголовки h1-h3."""
        headers = []
        for level in ("h1", "h2", "h3"):
            for h in soup.find_all(level):
                text = h.get_text(strip=True)
                if text:
                    headers.append(f"{level}: {text}")
        return headers
    
    def extract_tables(self, soup: BeautifulSoup) -> List[List[List[str]]]:
        """Извлечь таблицы как списки строк."""
        tables = []
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(rows)
        return tables
    
    def extract_lists(self, soup: BeautifulSoup) -> Dict[str, List[str]]:
        """Извлечь содержимое ul и ol."""
        result = {"ul": [], "ol": []}
        for tag_name in ("ul", "ol"):
            for lst in soup.find_all(tag_name):
                for li in lst.find_all("li", recursive=False):
                    text = li.get_text(strip=True)
                    if text:
                        result[tag_name].append(text)
        return result
    
    def _to_absolute(self, href: str, base_url: str) -> Optional[str]:
        """Преобразовать относительный URL в абсолютный."""
        if not href:
            return None
        try:
            if href.startswith(("http://", "https://")):
                return href
            if not base_url:
                return None
            return urljoin(base_url, href)
        except Exception:
            return None
    
    def _is_valid_url(self, url: str) -> bool:
        """Проверить, что URL корректен."""
        try:
            parsed = urlparse(url)
            return bool(parsed.scheme in ("http", "https") and parsed.netloc)
        except Exception:
            return False