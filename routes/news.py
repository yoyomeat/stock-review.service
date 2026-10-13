"""舆情路由 — JSON API only"""
import json
from pathlib import Path

from config import BASE_DIR

NEWS_DIR = BASE_DIR / 'data' / 'news'


def _news_path(date_str: str) -> Path:
    return NEWS_DIR / f'news_{date_str}.json'


def load_news(date_str: str) -> dict | None:
    """加载缓存的每日新闻数据"""
    if not date_str or not isinstance(date_str, str) or not (len(date_str) == 8 and date_str.isdigit()):
        return None
    p = _news_path(date_str)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            pass
    return None


def save_news(date_str: str, data: dict):
    """保存每日新闻数据"""
    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    p = _news_path(date_str)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def get_available_news_dates() -> list[str]:
    """获取所有有新闻数据的日期"""
    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    dates = []
    for fp in sorted(NEWS_DIR.glob('news_*.json')):
        ds = fp.stem.replace('news_', '')
        if len(ds) == 8 and ds.isdigit():
            dates.append(ds)
    return dates


def register_news_routes(app):

    @app.get('/api/news_dates')
    def api_news_dates():
        dates = get_available_news_dates()
        return {'dates': [{'date': d, 'display': f'{d[:4]}-{d[4:6]}-{d[6:]}'} for d in dates]}

    @app.get('/api/news/{date_str}')
    def api_news(date_str: str):
        data = load_news(date_str)
        if data is None:
            return {'error': 'no data', 'date': date_str}
        return data
