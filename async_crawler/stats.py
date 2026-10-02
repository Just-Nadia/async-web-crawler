"""Расширенная статистика краулера."""

import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict, Counter
from pathlib import Path

from .models import PageData


class CrawlerStats:
    """Расширенная статистика краулера."""
    
    def __init__(self):
        """Инициализация статистики."""
        self.start_time = None
        self.end_time = None
        
        # Основная статистика
        self.total_pages = 0
        self.successful_pages = 0
        self.failed_pages = 0
        self.retries = 0
        self.blocked_by_robots = 0
        
        # Детальная статистика
        self.status_codes = Counter()
        self.domain_stats = defaultdict(lambda: {
            "pages": 0,
            "success": 0,
            "failed": 0,
            "errors": [],
        })
        self.url_errors = {}
        self.performance = {
            "fetch_times": [],
            "parse_times": [],
            "total_time": 0,
        }
        
        # Временные метки для расчета скорости
        self._last_update = time.time()
        self._last_count = 0
        self.current_speed = 0.0
        
        # Оценка оставшегося времени
        self._avg_speed = 0.0
    
    def start(self) -> None:
        """Запустить таймер."""
        self.start_time = datetime.now()
        self._last_update = time.time()
        self._last_count = 0
    
    def stop(self) -> None:
        """Остановить таймер."""
        self.end_time = datetime.now()
    
    def add_page(self, url: str, data: Optional[PageData] = None) -> None:
        """Добавить информацию о странице."""
        self.total_pages += 1
        
        if data:
            self.successful_pages += 1
            
            # Статус код
            if data.status_code:
                self.status_codes[data.status_code] += 1
            
            # Доменная статистика
            domain = self._get_domain(url)
            self.domain_stats[domain]["pages"] += 1
            self.domain_stats[domain]["success"] += 1
    
    def add_error(
        self,
        url: str,
        error: str,
        error_type: str = "unknown"
    ) -> None:
        """Добавить информацию об ошибке."""
        self.total_pages += 1
        self.failed_pages += 1
        
        domain = self._get_domain(url)
        self.domain_stats[domain]["pages"] += 1
        self.domain_stats[domain]["failed"] += 1
        self.domain_stats[domain]["errors"].append({
            "url": url,
            "error": error,
            "type": error_type,
            "time": datetime.now().isoformat(),
        })
        
        self.url_errors[url] = {
            "error": error,
            "type": error_type,
        }
    
    def add_retry(self) -> None:
        """Добавить информацию о повторе."""
        self.retries += 1
    
    def add_blocked(self) -> None:
        """Добавить информацию о блокировке."""
        self.blocked_by_robots += 1
    
    def update_speed(self, current_count: int) -> None:
        """Обновить скорость."""
        now = time.time()
        elapsed = now - self._last_update
        
        if elapsed > 0:
            self.current_speed = (current_count - self._last_count) / elapsed
            # Обновляем среднюю скорость (сглаживание)
            self._avg_speed = self._avg_speed * 0.7 + self.current_speed * 0.3
        
        self._last_update = now
        self._last_count = current_count
    
    def get_eta(self, remaining: int) -> Optional[float]:
        """Получить оценку оставшегося времени."""
        if self._avg_speed <= 0:
            return None
        
        return remaining / self._avg_speed
    
    def _get_domain(self, url: str) -> str:
        """Извлечь домен из URL."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc or "unknown"
        except Exception:
            return "unknown"
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать статистику в словарь."""
        elapsed = 0
        if self.start_time and self.end_time:
            elapsed = (self.end_time - self.start_time).total_seconds()
        
        speed = 0
        if elapsed > 0:
            speed = self.total_pages / elapsed
        
        success_rate = 0
        if self.total_pages > 0:
            success_rate = self.successful_pages / self.total_pages * 100
        
        return {
            "summary": {
                "start_time": self.start_time.isoformat() if self.start_time else None,
                "end_time": self.end_time.isoformat() if self.end_time else None,
                "elapsed_seconds": elapsed,
                "total_pages": self.total_pages,
                "successful_pages": self.successful_pages,
                "failed_pages": self.failed_pages,
                "success_rate": success_rate,
                "pages_per_second": speed,
                "retries": self.retries,
                "blocked_by_robots": self.blocked_by_robots,
            },
            "status_codes": dict(self.status_codes),
            "domains": {
                domain: {
                    "pages": stats["pages"],
                    "success": stats["success"],
                    "failed": stats["failed"],
                    "errors": stats["errors"][:5],  # Только последние 5
                }
                for domain, stats in self.domain_stats.items()
            },
            "errors": {
                "total": len(self.url_errors),
                "by_type": self._count_error_types(),
            },
        }
    
    def _count_error_types(self) -> Dict[str, int]:
        """Посчитать ошибки по типам."""
        types = Counter()
        for error in self.url_errors.values():
            types[error.get("type", "unknown")] += 1
        return dict(types)
    
    def export_json(self, filename: str) -> None:
        """Экспортировать статистику в JSON."""
        data = self.to_dict()
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def export_html_report(self, filename: str) -> None:
        """Экспортировать статистику в HTML отчет."""
        stats = self.to_dict()
        summary = stats["summary"]
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Отчет краулера</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1, h2 {{ color: #333; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
        .stat-card {{ background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 28px; font-weight: bold; color: #007bff; }}
        .stat-label {{ color: #666; font-size: 14px; margin-top: 5px; }}
        .success {{ color: #28a745; }}
        .failed {{ color: #dc3545; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f8f9fa; }}
        .progress-bar {{ background: #e9ecef; border-radius: 10px; overflow: hidden; height: 20px; }}
        .progress-fill {{ background: #28a745; height: 100%; transition: width 0.3s; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Отчет краулера</h1>
        <p><em>Сгенерировано: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</em></p>
        
        <h2>📋 Сводка</h2>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{summary.get('total_pages', 0)}</div>
                <div class="stat-label">Всего страниц</div>
            </div>
            <div class="stat-card">
                <div class="stat-value success">{summary.get('successful_pages', 0)}</div>
                <div class="stat-label">Успешно</div>
            </div>
            <div class="stat-card">
                <div class="stat-value failed">{summary.get('failed_pages', 0)}</div>
                <div class="stat-label">Ошибок</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{summary.get('success_rate', 0):.1f}%</div>
                <div class="stat-label">Успешность</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{summary.get('pages_per_second', 0):.2f}</div>
                <div class="stat-label">Скорость (стр/сек)</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{summary.get('elapsed_seconds', 0):.1f}с</div>
                <div class="stat-label">Время работы</div>
            </div>
        </div>
        
        <h2>📊 Статус-коды</h2>
        <table>
            <tr>
                <th>Код</th>
                <th>Количество</th>
                <th>Распределение</th>
            </tr>
        """
        
        total = sum(stats["status_codes"].values()) or 1
        for code, count in sorted(stats["status_codes"].items()):
            percent = count / total * 100
            html += f"""
            <tr>
                <td><strong>{code}</strong></td>
                <td>{count}</td>
                <td>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: {percent}%; background: {self._get_color(code)};"></div>
                    </div>
                </td>
            </tr>
            """
        
        html += """
        </table>
        
        <h2>🌐 Домены</h2>
        <table>
            <tr>
                <th>Домен</th>
                <th>Страниц</th>
                <th>Успешно</th>
                <th>Ошибок</th>
            </tr>
        """
        
        for domain, domain_stats in sorted(
            stats["domains"].items(),
            key=lambda x: x[1]["pages"],
            reverse=True
        )[:20]:
            html += f"""
            <tr>
                <td>{domain}</td>
                <td>{domain_stats['pages']}</td>
                <td class="success">{domain_stats['success']}</td>
                <td class="failed">{domain_stats['failed']}</td>
            </tr>
            """
        
        html += f"""
        </table>
        
        <h2>❌ Ошибки</h2>
        <p>Всего ошибок: <strong>{stats['errors']['total']}</strong></p>
        <p>По типам: {', '.join(f"{k}: {v}" for k, v in stats['errors']['by_type'].items())}</p>
        
        <hr>
        <p><em>Сгенерировано AsyncCrawler v1.0</em></p>
    </div>
</body>
</html>
"""
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html)
    
    def _get_color(self, code: int) -> str:
        """Получить цвет для статус-кода."""
        if 200 <= code < 300:
            return "#28a745"  # Зеленый
        elif 300 <= code < 400:
            return "#17a2b8"  # Синий
        elif 400 <= code < 500:
            return "#ffc107"  # Желтый
        elif 500 <= code < 600:
            return "#dc3545"  # Красный
        return "#6c757d"  # Серый