"""Тесты для статистики."""

import json
import tempfile
from pathlib import Path

import pytest

from async_crawler.stats import CrawlerStats
from async_crawler.models import PageData


def test_stats_basic():
    """Тест базовой статистики."""
    stats = CrawlerStats()
    stats.start()
    
    stats.add_page("https://example.com/1", PageData(url="https://example.com/1", status_code=200))
    stats.add_page("https://example.com/2", PageData(url="https://example.com/2", status_code=200))
    stats.add_error("https://example.com/3", "404 Not Found")
    
    stats.stop()
    
    data = stats.to_dict()
    summary = data['summary']
    
    assert summary['total_pages'] == 3
    assert summary['successful_pages'] == 2
    assert summary['failed_pages'] == 1
    assert summary['success_rate'] == 66.66666666666666


def test_stats_status_codes():
    """Тест статус-кодов."""
    stats = CrawlerStats()
    stats.start()
    
    stats.add_page("https://example.com/1", PageData(url="https://example.com/1", status_code=200))
    stats.add_page("https://example.com/2", PageData(url="https://example.com/2", status_code=200))
    stats.add_page("https://example.com/3", PageData(url="https://example.com/3", status_code=404))
    
    stats.stop()
    
    data = stats.to_dict()
    assert data['status_codes'][200] == 2
    assert data['status_codes'][404] == 1


def test_stats_domains():
    """Тест статистики по доменам."""
    stats = CrawlerStats()
    stats.start()
    
    stats.add_page("https://example.com/1", PageData(url="https://example.com/1", status_code=200))
    stats.add_page("https://example.com/2", PageData(url="https://example.com/2", status_code=200))
    stats.add_error("https://other.org/page", "Error")
    
    stats.stop()
    
    data = stats.to_dict()
    assert 'example.com' in data['domains']
    assert data['domains']['example.com']['pages'] == 2
    assert 'other.org' in data['domains']


def test_stats_speed():
    """Тест скорости."""
    stats = CrawlerStats()
    
    stats.update_speed(10)
    # Имитируем прошедшее время
    import time
    time.sleep(0.1)
    stats.update_speed(20)
    
    assert stats.current_speed >= 0


def test_stats_export_json():
    """Тест экспорта в JSON."""
    stats = CrawlerStats()
    stats.start()
    stats.add_page("https://example.com", PageData(url="https://example.com", status_code=200))
    stats.stop()
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        stats.export_json(f.name)
        
        with open(f.name, 'r', encoding='utf-8') as read_f:
            data = json.load(read_f)
            assert 'summary' in data
            assert data['summary']['total_pages'] == 1


def test_stats_export_html():
    """Тест экспорта в HTML."""
    stats = CrawlerStats()
    stats.start()
    stats.add_page("https://example.com", PageData(url="https://example.com", status_code=200))
    stats.stop()
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        stats.export_html_report(f.name)
        
        with open(f.name, 'r', encoding='utf-8') as read_f:
            content = read_f.read()
            assert "<!DOCTYPE html>" in content
            assert "Отчет краулера" in content