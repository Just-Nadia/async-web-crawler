"""CLI интерфейс для краулера."""

import argparse
import asyncio
import sys
from typing import List, Optional

from .advanced_crawler import AdvancedCrawler
from .logger import setup_logging, get_logger


def parse_args():
    """Парсинг аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description="AsyncCrawler - Асинхронный веб-краулер",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python -m async_crawler.cli --urls https://example.com --max-pages 50
  python -m async_crawler.cli --config config.yaml
  python -m async_crawler.cli --urls https://example.com --output results.json --max-depth 2
        """
    )
    
    # Основные аргументы
    parser.add_argument(
        '--urls',
        nargs='+',
        help='Стартовые URL для краулинга'
    )
    
    parser.add_argument(
        '--config',
        help='Путь к конфигурационному файлу (YAML или JSON)'
    )
    
    # Настройки краулинга
    parser.add_argument(
        '--max-pages',
        type=int,
        default=100,
        help='Максимальное количество страниц (по умолчанию: 100)'
    )
    
    parser.add_argument(
        '--max-depth',
        type=int,
        default=3,
        help='Максимальная глубина обхода (по умолчанию: 3)'
    )
    
    parser.add_argument(
        '--max-concurrent',
        type=int,
        default=10,
        help='Максимальное количество параллельных запросов (по умолчанию: 10)'
    )
    
    parser.add_argument(
        '--rate-limit',
        type=float,
        default=1.0,
        help='Лимит запросов в секунду (по умолчанию: 1.0)'
    )
    
    # Опции
    parser.add_argument(
        '--respect-robots',
        action='store_true',
        default=True,
        help='Соблюдать robots.txt (включено по умолчанию)'
    )
    
    parser.add_argument(
        '--no-respect-robots',
        action='store_false',
        dest='respect_robots',
        help='Не соблюдать robots.txt'
    )
    
    parser.add_argument(
        '--use-sitemap',
        action='store_true',
        help='Использовать sitemap для получения URL'
    )
    
    parser.add_argument(
        '--same-domain',
        action='store_true',
        default=True,
        help='Только URL того же домена (по умолчанию: True)'
    )
    
    parser.add_argument(
        '--no-same-domain',
        action='store_false',
        dest='same_domain',
        help='Разрешить URL других доменов'
    )
    
    # Вывод
    parser.add_argument(
        '--output',
        help='Файл для сохранения результатов (JSON)'
    )
    
    parser.add_argument(
        '--report',
        help='Файл для сохранения HTML отчета'
    )
    
    parser.add_argument(
        '--data-export',
        help='Файл для экспорта собранных данных'
    )
    
    parser.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Уровень логирования (по умолчанию: INFO)'
    )
    
    parser.add_argument(
        '--no-progress',
        action='store_true',
        help='Не показывать прогресс'
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version='AsyncCrawler v1.0'
    )
    
    return parser.parse_args()


def create_crawler_from_args(args) -> AdvancedCrawler:
    """Создать краулер из аргументов CLI."""
    if args.config:
        return AdvancedCrawler.from_config(args.config)
    
    from .config import CrawlerConfig
    
    config = CrawlerConfig(
        max_concurrent=args.max_concurrent,
        max_depth=args.max_depth,
        max_pages=args.max_pages,
        requests_per_second=args.rate_limit,
        respect_robots=args.respect_robots,
        same_domain_only=args.same_domain,
        log_level=args.log_level,
    )
    
    return AdvancedCrawler(config=config)


async def async_main():
    """Асинхронная основная функция."""
    args = parse_args()
    
    # Настраиваем логирование
    setup_logging(level=args.log_level)
    logger = get_logger(__name__)
    
    # Проверяем аргументы
    if not args.config and not args.urls:
        logger.error("Необходимо указать --urls или --config")
        sys.exit(1)
    
    try:
        # Создаем краулер
        crawler = create_crawler_from_args(args)
        
        # Получаем стартовые URL: сначала из аргументов, потом из конфига
        start_urls = args.urls
        if not start_urls:
            start_urls = getattr(crawler.config, "start_urls", None) or []
        
        if not start_urls:
            logger.error(
                "Не указаны стартовые URL. "
                "Передайте --urls https://... или добавьте start_urls в конфиг."
            )
            sys.exit(1)
        
        logger.info(f"Запуск краулера с URL: {start_urls[:5]}...")
        
        # Запускаем краулинг
        results = await crawler.crawl(
            start_urls=start_urls,
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            use_sitemap=args.use_sitemap,
            show_progress=not args.no_progress,
        )
        
        # Получаем статистику
        stats = crawler.get_stats()
        summary = stats['summary']
        
        logger.info("=" * 60)
        logger.info("📊 ИТОГОВАЯ СТАТИСТИКА")
        logger.info("=" * 60)
        logger.info(f"  Всего страниц: {summary['total_pages']}")
        logger.info(f"  Успешно: {summary['successful_pages']}")
        logger.info(f"  Ошибок: {summary['failed_pages']}")
        logger.info(f"  Успешность: {summary['success_rate']:.1f}%")
        logger.info(f"  Скорость: {summary['pages_per_second']:.2f} стр/сек")
        logger.info(f"  Время работы: {summary['elapsed_seconds']:.1f}с")
        
        # Экспорт
        if args.output:
            crawler.export_json(args.output)
            logger.info(f"  Статистика сохранена в {args.output}")
        
        if args.report:
            crawler.export_html_report(args.report)
            logger.info(f"  HTML отчет сохранен в {args.report}")
        
        if args.data_export:
            crawler.export_data(args.data_export)
            logger.info(f"  Данные экспортированы в {args.data_export}")
        
        # Закрываем краулер
        await crawler.close()
        
        logger.info("✅ Краулинг завершен успешно")
        
    except KeyboardInterrupt:
        logger.warning("🛑 Краулинг прерван пользователем")
        sys.exit(130)
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    """Основная точка входа."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()