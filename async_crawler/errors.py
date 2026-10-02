"""Классы ошибок для краулера."""

from typing import Optional


class CrawlerError(Exception):
    """Базовое исключение краулера."""
    
    def __init__(self, message: str, url: Optional[str] = None):
        self.url = url
        self.message = message
        super().__init__(f"{message} (URL: {url})" if url else message)


class TransientError(CrawlerError):
    """Временная ошибка — имеет смысл повторить.
    
    Примеры: таймаут, 429, 503, временная недоступность.
    """
    pass


class PermanentError(CrawlerError):
    """Постоянная ошибка — повторять бессмысленно.
    
    Примеры: 404, 403, 401, 410.
    """
    pass


class NetworkError(CrawlerError):
    """Сетевая ошибка — соединение, DNS.
    
    Обычно имеет смысл повторить.
    """
    pass


class ParseError(CrawlerError):
    """Ошибка парсинга HTML.
    
    Повтор обычно не помогает — контент уже получен.
    """
    pass


class RobotsBlockedError(PermanentError):
    """URL запрещён robots.txt."""
    pass


class RateLimitError(TransientError):
    """Превышен лимит запросов (429)."""
    
    def __init__(self, message: str, url: Optional[str] = None, retry_after: Optional[float] = None):
        self.retry_after = retry_after
        super().__init__(message, url)


class CircuitBreakerOpenError(TransientError):
    """Circuit breaker разомкнут — домен временно заблокирован."""
    pass


def classify_http_error(status_code: int, url: Optional[str] = None) -> CrawlerError:
    """Классифицировать HTTP-статус в подходящее исключение."""
    if status_code == 429:
        return RateLimitError(f"HTTP 429 Too Many Requests", url)
    if status_code in (500, 502, 503, 504):
        return TransientError(f"HTTP {status_code} (временная ошибка сервера)", url)
    if status_code in (400, 401, 403, 404, 405, 410):
        return PermanentError(f"HTTP {status_code}", url)
    if 400 <= status_code < 500:
        return PermanentError(f"HTTP {status_code} (клиентская ошибка)", url)
    if 500 <= status_code < 600:
        return TransientError(f"HTTP {status_code} (серверная ошибка)", url)
    return CrawlerError(f"HTTP {status_code}", url)