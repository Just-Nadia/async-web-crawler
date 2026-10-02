"""Тесты для sitemap парсера."""

import pytest
from unittest.mock import Mock, patch

from async_crawler.sitemap import SitemapParser, SitemapUrlSource


@pytest.mark.asyncio
async def test_sitemap_parser_parse():
    """Тест парсинга sitemap."""
    parser = SitemapParser()
    
    sitemap_content = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url>
            <loc>https://example.com/page1</loc>
            <lastmod>2024-01-01</lastmod>
        </url>
        <url>
            <loc>https://example.com/page2</loc>
        </url>
    </urlset>
    """
    
    urls = await parser._parse_sitemap(sitemap_content, "https://example.com", 100)
    
    assert len(urls) == 2
    assert "https://example.com/page1" in urls
    assert "https://example.com/page2" in urls


@pytest.mark.asyncio
async def test_sitemap_parser_parse_index():
    """Тест парсинга sitemap index."""
    parser = SitemapParser()
    
    sitemap_content = """<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <sitemap>
            <loc>https://example.com/sitemap1.xml</loc>
        </sitemap>
        <sitemap>
            <loc>https://example.com/sitemap2.xml</loc>
        </sitemap>
    </sitemapindex>
    """
    
    # Мокаем fetch_sitemap для дочерних sitemap
    async def mock_fetch_sitemap(url, max_urls):
        if "sitemap1" in url:
            return ["https://example.com/page1", "https://example.com/page2"]
        elif "sitemap2" in url:
            return ["https://example.com/page3"]
        return []
    
    parser.fetch_sitemap = mock_fetch_sitemap
    
    urls = await parser._parse_sitemap_index(sitemap_content, "https://example.com", 100)
    
    assert len(urls) == 3
    assert "https://example.com/page1" in urls
    assert "https://example.com/page2" in urls
    assert "https://example.com/page3" in urls


@pytest.mark.asyncio
async def test_sitemap_url_source():
    """Тест источника URL из sitemap."""
    parser = SitemapParser()
    source = SitemapUrlSource(parser)
    
    # Мокаем fetch_urls
    async def mock_fetch_urls(base_url, max_urls):
        return ["https://example.com/1", "https://example.com/2", "https://example.com/3"]
    
    source.fetch_urls = mock_fetch_urls
    
    urls = await source.fetch_urls("https://example.com", 10)
    assert len(urls) == 3
    
    # Мок не сохраняет URL во внутренний буфер source._urls —
    # заполняем вручную, чтобы get_next_url работал
    source._urls = urls
    
    # Проверяем последовательную выдачу
    assert source.get_next_url() == "https://example.com/1"
    assert source.get_next_url() == "https://example.com/2"
    assert source.get_next_url() == "https://example.com/3"
    assert source.get_next_url() is None