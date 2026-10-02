#!/usr/bin/env python3
"""AsyncCrawler - Асинхронный веб-краулер.

Usage:
    python -m async_crawler [OPTIONS]

Examples:
    python -m async_crawler --urls https://example.com --max-pages 50
    python -m async_crawler --config config.yaml
    python -m async_crawler --urls https://example.com --output stats.json --report report.html
"""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())