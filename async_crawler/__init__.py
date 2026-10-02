"""Async Web Crawler - Асинхронный веб-краулер."""

__version__ = "1.0.0"
__author__ = "Your Name"

from .advanced_crawler import AdvancedCrawler
from .crawler import AsyncCrawler
from .config import CrawlerConfig, default_config
from .storage import JSONStorage, CSVStorage, SQLiteStorage, MultiStorage
from .models import PageData, CrawlResult

__all__ = [
    "AdvancedCrawler",
    "AsyncCrawler",
    "CrawlerConfig",
    "default_config",
    "JSONStorage",
    "CSVStorage",
    "SQLiteStorage",
    "MultiStorage",
    "PageData",
    "CrawlResult",
]