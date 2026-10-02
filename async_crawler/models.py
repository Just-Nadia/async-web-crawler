"""Модели данных для краулера."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional


@dataclass
class PageData:
    """Данные одной загруженной страницы."""
    
    url: str
    status_code: int = 0
    title: str = ""
    text: str = ""
    html: str = ""
    links: List[str] = field(default_factory=list)
    images: List[Dict[str, str]] = field(default_factory=list)
    headers: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    content_type: str = ""
    content_length: int = 0
    crawled_at: datetime = field(default_factory=datetime.now)
    depth: int = 0
    fetch_time: float = 0.0
    parse_time: float = 0.0
    
    @property
    def links_count(self) -> int:
        return len(self.links)
    
    @property
    def images_count(self) -> int:
        return len(self.images)
    
    @property
    def text_length(self) -> int:
        return len(self.text) if self.text else 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь (для JSON/CSV/БД)."""
        data = asdict(self)
        data['crawled_at'] = self.crawled_at.isoformat()
        data['links_count'] = self.links_count
        data['images_count'] = self.images_count
        data['text_length'] = self.text_length
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PageData":
        """Создать из словаря."""
        data = dict(data)
        if isinstance(data.get('crawled_at'), str):
            try:
                data['crawled_at'] = datetime.fromisoformat(data['crawled_at'])
            except ValueError:
                data['crawled_at'] = datetime.now()
        # Отбрасываем вычисляемые поля, которых нет в конструкторе
        for key in ('links_count', 'images_count', 'text_length'):
            data.pop(key, None)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CrawlResult:
    """Результат краулинга целиком (для сериализации)."""
    
    start_urls: List[str] = field(default_factory=list)
    pages: List[PageData] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    
    @property
    def total_pages(self) -> int:
        return len(self.pages)
    
    @property
    def total_errors(self) -> int:
        return len(self.errors)
    
    @property
    def elapsed_seconds(self) -> float:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_urls": self.start_urls,
            "total_pages": self.total_pages,
            "total_errors": self.total_errors,
            "elapsed_seconds": self.elapsed_seconds,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "pages": [p.to_dict() for p in self.pages],
            "errors": self.errors,
        }