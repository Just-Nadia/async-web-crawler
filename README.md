# Async Web Crawler

Асинхронный веб-краулер на Python с поддержкой конкурентности, очередей, rate limiting, соблюдения robots.txt и сохранения данных в JSON/CSV/SQLite.

## Возможности

- Асинхронная загрузка страниц через `aiohttp` с connection pooling
- Управление конкурентностью: глобальные и per-domain семафоры
- Rate limiting с настраиваемыми задержками и jitter
- Парсинг HTML через `BeautifulSoup` + `lxml`
- Очередь URL с приоритетами, фильтрацией и контролем глубины
- Обработка ошибок с экспоненциальным backoff и Circuit Breaker
- Соблюдение `robots.txt` с кэшированием
- Сохранение данных в JSON, CSV, SQLite или всё сразу
- Расширенная статистика и HTML-отчёты
- Поддержка `sitemap.xml`
- CLI-интерфейс и конфигурация через YAML

## Установка

```bash
pip install -r requirements.txt
```

Или, если хотите установить как пакет:

```bash
pip install -e .
```

## Быстрый старт

Запуск из командной строки:

```bash
python -m async_crawler --urls https://example.com --max-pages 10
```

Или через Python API:

```python
import asyncio
from async_crawler import AsyncCrawler


async def main():
    crawler = AsyncCrawler(max_concurrent=10, max_depth=2)
    results = await crawler.crawl(start_urls=["https://example.com"], max_pages=10)
    for url, page in results.items():
        print(url, page.title)
    await crawler.close()


asyncio.run(main())
```

## CLI

```
python -m async_crawler --help
```

Основные аргументы:

| Аргумент | Описание |
|---|---|
| `--urls URL [URL ...]` | Стартовые URL |
| `--config FILE` | Путь к YAML/JSON конфигу |
| `--max-pages N` | Максимум страниц |
| `--max-depth N` | Максимальная глубина обхода |
| `--max-concurrent N` | Максимум одновременных запросов |
| `--rate-limit N` | Лимит запросов в секунду |
| `--respect-robots` | Соблюдать robots.txt |
| `--use-sitemap` | Использовать sitemap.xml |
| `--output FILE` | Сохранить статистику в JSON |
| `--report FILE` | Сохранить HTML-отчёт |
| `--data-export FILE` | Экспортировать собранные данные |

## Конфигурация

Все параметры можно задать в `config.yaml`. Пример:

```yaml
max_concurrent: 10
max_depth: 3
max_pages: 100
requests_per_second: 1.0
respect_robots: true
user_agent: "AsyncCrawler/1.0"

retry:
  max_retries: 3
  backoff_factor: 2.0

storage:
  storage_type: "sqlite"
  sqlite_db: "crawler.db"
```

## Структура проекта

```
async_crawler/
├── __init__.py          # Публичный API
├── __main__.py          # Точка входа для python -m async_crawler
├── cli.py               # CLI
├── advanced_crawler.py  # Интеграция всех компонентов
├── crawler.py           # Основной краулер
├── parser.py            # Парсинг HTML
├── queue.py             # Очередь и семафоры
├── rate_limiter.py      # Rate limiting
├── robots.py            # robots.txt
├── retry.py             # Retry + Circuit Breaker
├── storage.py           # JSON/CSV/SQLite хранилища
├── stats.py             # Статистика и отчёты
├── sitemap.py           # Sitemap
├── config.py            # Конфигурация
├── models.py            # Модели данных
├── errors.py            # Исключения
└── logger.py            # Логирование
```

## Тестирование

```bash
pytest
```

## Лицензия

MIT