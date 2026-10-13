"""行业日历路由 — JSON API only"""
import json

from config import BASE_DIR

EVENTS_DIR = BASE_DIR / 'data' / 'events'


def load_events(year: int, month: int) -> dict | None:
    path = EVENTS_DIR / f'events_{year:04d}{month:02d}.json'
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            pass
    return None


def get_available_months() -> list[str]:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    months = []
    for fp in sorted(EVENTS_DIR.glob('events_*.json')):
        ds = fp.stem.replace('events_', '')
        if len(ds) == 6 and ds.isdigit():
            months.append(ds)
    return months


def register_events_routes(app):

    @app.get('/api/events/{month}')
    def api_events(month: str):
        if len(month) != 6 or not month.isdigit():
            return {'error': 'invalid month format, use YYYYMM'}
        y, m = int(month[:4]), int(month[4:6])
        data = load_events(y, m)
        if data is None:
            return {'error': 'no data', 'month': month}
        return data
