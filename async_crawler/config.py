"""Конфигурация краулера."""

from dataclasses import dataclass, field, fields
from typing import List, Dict, Any, Optional


@dataclass
class RetryConfig:
    """Настройки повторов."""
    
    max_retries: int = 3
    backoff_factor: float = 2.0
    initial_delay: float = 1.0
    max_delay: float = 60.0
    retry_on_status_codes: List[int] = field(
        default_factory=lambda: [429, 500, 502, 503, 504]
    )
    no_retry_status_codes: List[int] = field(
        default_factory=lambda: [400, 401, 403, 404, 405, 410]
    )
    
    def should_retry_status(self, status_code: int) -> bool:
        """Нужно ли повторять при данном статусе."""
        if status_code in self.no_retry_status_codes:
            return False
        return status_code in self.retry_on_status_codes


@dataclass
class CircuitBreakerConfig:
    """Настройки circuit breaker."""
    
    enabled: bool = True
    failure_threshold: int = 5
    success_threshold: int = 3
    timeout: float = 30.0
    half_open_max_calls: int = 3
    reset_timeout: float = 60.0


@dataclass
class StorageConfig:
    """Настройки хранения данных."""
    
    storage_type: str = "json"
    json_file: str = "crawler_results.json"
    json_indent: int = 2
    json_ensure_ascii: bool = False
    csv_file: str = "crawler_results.csv"
    csv_delimiter: str = ","
    csv_encoding: str = "utf-8"
    sqlite_db: str = "crawler.db"
    sqlite_batch_size: int = 100
    batch_size: int = 100
    flush_interval: float = 5.0


@dataclass
class CrawlerConfig:
    """Основная конфигурация краулера."""
    
    max_concurrent: int = 10
    max_depth: int = 3
    max_pages: int = 100
    requests_per_second: float = 1.0
    
    min_delay: float = 0.5
    max_delay: float = 10.0
    jitter: float = 0.3
    delay_between_requests: float = 0.5
    
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    total_timeout: float = 60.0
    
    user_agent: str = "AsyncCrawler/1.0 (+https://github.com/example/crawler)"
    rotate_user_agent: bool = False
    user_agents: List[str] = field(default_factory=list)
    
    respect_robots: bool = True
    robots_cache_ttl: float = 3600.0
    robots_user_agent: str = "AsyncCrawler"
    
    same_domain_only: bool = True
    exclude_patterns: List[str] = field(default_factory=list)
    include_patterns: List[str] = field(default_factory=list)
    
    retry: RetryConfig = field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    
    log_level: str = "INFO"
    log_file: str = "crawler.log"
    
    show_progress: bool = True
    progress_interval: float = 1.0
    
    start_urls: List[str] = field(default_factory=list)
    
    parse_html: bool = True
    extract_links: bool = True
    extract_text: bool = True
    extract_metadata: bool = True
    
    proxy: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь (рекурсивно)."""
        result = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if hasattr(value, 'to_dict'):
                result[f.name] = value.to_dict()
            elif isinstance(value, list) and value and hasattr(value[0], 'to_dict'):
                result[f.name] = [v.to_dict() for v in value]
            else:
                result[f.name] = value
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CrawlerConfig":
        """Создать конфигурацию из словаря (например, из YAML)."""
        data = dict(data)
        
        nested = {
            'retry': RetryConfig,
            'circuit_breaker': CircuitBreakerConfig,
            'storage': StorageConfig,
        }
        for key, config_cls in nested.items():
            if key in data and isinstance(data[key], dict):
                data[key] = _dict_to_dataclass(config_cls, data[key])
        
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


def _dict_to_dataclass(cls, data: Dict[str, Any]):
    """Заполнить dataclass из словаря, игнорируя неизвестные ключи."""
    known = {f.name for f in fields(cls)}
    filtered = {k: v for k, v in data.items() if k in known}
    return cls(**filtered)


def default_config() -> CrawlerConfig:
    """Конфигурация по умолчанию."""
    return CrawlerConfig()