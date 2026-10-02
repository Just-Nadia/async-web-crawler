"""AdvancedCrawler - полная интеграция всех компонентов."""

import asyncio
import json
import time
from datetime import datetime
from typing import List, Dict, Optional, Any, Union
from pathlib import Path

import yaml

from .crawler import AsyncCrawler
from .storage import JSONStorage, CSVStorage, SQLiteStorage, MultiStorage, DataStorage
from .sitemap import SitemapParser, SitemapUrlSource
from .stats import CrawlerStats
from .config import CrawlerConfig
from .logger import setup_logging, get_logger


class AdvancedCrawler:
    """Расширенный краулер с полной интеграцией компонентов."""
    
    def __init__(
        self,
        config: Optional[CrawlerConfig] = None,
        config_file: Optional[str] = None,
        storage: Optional[DataStorage] = None,
    ):
        """Инициализация AdvancedCrawler.
        
        Args:
            config: Конфигурация краулера
            config_file: Путь к конфигурационному файлу
            storage: Хранилище данных
        """
        # Загружаем конфигурацию
        if config_file:
            self.config = self._load_config(config_file)
        elif config:
            self.config = config
        else:
            self.config = CrawlerConfig()
        
        # Настраиваем логирование
        self.logger = get_logger(__name__)
        self._setup_logging()
        
        # Создаем хранилище если не передано
        if storage is None:
            storage = self._create_storage()
        
        # Создаем краулер
        self.crawler = AsyncCrawler(
            max_concurrent=self.config.max_concurrent,
            max_depth=self.config.max_depth,
            max_pages=self.config.max_pages,
            requests_per_second=self.config.requests_per_second,
            respect_robots=self.config.respect_robots,
            user_agent=self.config.user_agent,
            config=self.config,
            storage=storage,
        )
        
        # Sitemap
        self.sitemap_parser = SitemapParser()
        self.sitemap_source = SitemapUrlSource(self.sitemap_parser)
        
        # Статистика
        self.stats = CrawlerStats()
        
        # Результаты
        self.results = {}
        self._start_urls = []
    
    def _load_config(self, config_file: str) -> CrawlerConfig:
        """Загрузить конфигурацию из файла."""
        with open(config_file, 'r', encoding='utf-8') as f:
            if config_file.endswith('.yaml') or config_file.endswith('.yml'):
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
        
        return self._dict_to_config(data)
    
    def _dict_to_config(self, data: Dict) -> CrawlerConfig:
        """Преобразовать словарь в конфигурацию."""
        config = CrawlerConfig()
        
        for key, value in data.items():
            if hasattr(config, key):
                if key == 'retry' and isinstance(value, dict):
                    from .config import RetryConfig
                    retry_config = RetryConfig()
                    for k, v in value.items():
                        if hasattr(retry_config, k):
                            setattr(retry_config, k, v)
                    setattr(config, key, retry_config)
                elif key == 'circuit_breaker' and isinstance(value, dict):
                    from .config import CircuitBreakerConfig
                    cb_config = CircuitBreakerConfig()
                    for k, v in value.items():
                        if hasattr(cb_config, k):
                            setattr(cb_config, k, v)
                    setattr(config, key, cb_config)
                elif key == 'storage' and isinstance(value, dict):
                    from .config import StorageConfig
                    storage_config = StorageConfig()
                    for k, v in value.items():
                        if hasattr(storage_config, k):
                            setattr(storage_config, k, v)
                    setattr(config, key, storage_config)
                else:
                    setattr(config, key, value)
        
        return config
    
    def _setup_logging(self) -> None:
        """Настроить логирование."""
        setup_logging(
            level=self.config.log_level,
            log_file=self.config.log_file,
        )
    
    def _create_storage(self) -> DataStorage:
        """Создать хранилище на основе конфигурации."""
        storage_config = self.config.storage
        
        if storage_config.storage_type == "json":
            return JSONStorage(
                file_path=storage_config.json_file,
                indent=storage_config.json_indent,
                ensure_ascii=storage_config.json_ensure_ascii,
            )
        elif storage_config.storage_type == "csv":
            return CSVStorage(
                file_path=storage_config.csv_file,
                delimiter=storage_config.csv_delimiter,
                encoding=storage_config.csv_encoding,
            )
        elif storage_config.storage_type == "sqlite":
            return SQLiteStorage(
                db_path=storage_config.sqlite_db,
                batch_size=storage_config.sqlite_batch_size,
            )
        elif storage_config.storage_type == "multi":
            return MultiStorage([
                JSONStorage(storage_config.json_file),
                CSVStorage(storage_config.csv_file),
                SQLiteStorage(storage_config.sqlite_db),
            ])
        else:
            return JSONStorage("crawler_results.json")
    
    async def crawl(
        self,
        start_urls: Optional[List[str]] = None,
        use_sitemap: bool = False,
        max_pages: Optional[int] = None,
        max_depth: Optional[int] = None,
        show_progress: bool = True,
    ) -> Dict[str, Any]:
        """Запустить краулинг.
        
        Args:
            start_urls: Стартовые URL
            use_sitemap: Использовать sitemap для получения URL
            max_pages: Максимальное количество страниц
            max_depth: Максимальная глубина
            show_progress: Показывать прогресс
            
        Returns:
            Dict[str, Any]: Результаты краулинга
        """
        # Определяем стартовые URL
        self._start_urls = start_urls or self._start_urls or []
        
        if not self._start_urls:
            raise ValueError("Не указаны стартовые URL")
        
        # Если используем sitemap, добавляем URL из sitemap
        if use_sitemap:
            all_urls = []
            for base_url in self._start_urls:
                sitemap_urls = await self.sitemap_source.fetch_urls(
                    base_url,
                    max_pages or 1000
                )
                all_urls.extend(sitemap_urls)
            
            if all_urls:
                self.logger.info(f"Получено {len(all_urls)} URL из sitemap")
                self._start_urls = all_urls[:max_pages] if max_pages else all_urls
        
        # Запускаем статистику
        self.stats.start()
        
        # Краулинг
        self.results = await self.crawler.crawl(
            start_urls=self._start_urls,
            max_pages=max_pages,
            max_depth=max_depth,
            show_progress=show_progress,
        )
        
        # Останавливаем статистику
        self.stats.stop()
        
        # Обновляем статистику из краулера
        crawler_stats = self.crawler.get_stats()
        for page_data in self.results.values():
            self.stats.add_page(page_data.url, page_data)
        
        # Добавляем ошибки
        for url, error_info in self.crawler.error_results.items():
            self.stats.add_error(
                url,
                error_info.get('error', 'Unknown'),
                error_info.get('error_type', 'unknown')
            )
        
        self.stats.retries = crawler_stats.get('retries', 0)
        self.stats.blocked_by_robots = crawler_stats.get('blocked_by_robots', 0)
        
        self.logger.info(f"Краулинг завершен. Обработано: {len(self.results)} страниц")
        
        return self.results
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику."""
        return self.stats.to_dict()
    
    def get_error_report(self) -> str:
        """Получить отчет об ошибках."""
        if hasattr(self.crawler, 'get_error_report'):
            return self.crawler.get_error_report()
        return "Отчет об ошибках недоступен"
    
    def export_json(self, filename: str) -> None:
        """Экспортировать результаты в JSON."""
        self.stats.export_json(filename)
        self.logger.info(f"Статистика экспортирована в {filename}")
    
    def export_html_report(self, filename: str) -> None:
        """Экспортировать отчет в HTML."""
        self.stats.export_html_report(filename)
        self.logger.info(f"HTML отчет экспортирован в {filename}")
    
    def export_data(self, filename: str) -> None:
        """Экспортировать собранные данные в JSON."""
        data = {
            "metadata": {
                "total_pages": len(self.results),
                "crawled_at": datetime.now().isoformat(),
                "start_urls": self._start_urls[:10],
            },
            "pages": [
                {
                    "url": url,
                    "title": data.title,
                    "text": data.text[:500] if data.text else "",
                    "links_count": data.links_count,
                    "images_count": data.images_count,
                    "status_code": data.status_code,
                }
                for url, data in self.results.items()
            ]
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        
        self.logger.info(f"Данные экспортированы в {filename}")
    
    async def close(self) -> None:
        """Закрыть все ресурсы."""
        await self.crawler.close()
        await self.sitemap_parser.close()
        self.logger.info("Краулер закрыт")
    
    @classmethod
    def from_config(cls, config_file: str) -> 'AdvancedCrawler':
        """Создать краулер из конфигурационного файла."""
        return cls(config_file=config_file)

