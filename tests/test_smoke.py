"""Smoke tests — 只验证"能不能通"，不涉及业务逻辑"""


def test_health(client):
    """健康检查"""
    r = client.get('/health')
    assert r.status_code == 200
    data = r.json()
    assert data['status'] == 'ok'


def test_api_dates(client):
    """日期列表 API"""
    r = client.get('/api/dates')
    assert r.status_code == 200
    dates = r.json()
    assert isinstance(dates, list)
    assert len(dates) > 0


def test_api_review(client):
    """单日复盘数据 API"""
    dates = client.get('/api/dates').json()
    latest = dates[-1]['date'] if isinstance(dates[-1], dict) else dates[-1]
    r = client.get(f'/api/review/{latest}')
    assert r.status_code == 200


def test_api_trend(client):
    """趋势数据 API"""
    r = client.get('/api/trend')
    assert r.status_code == 200


def test_api_dashboard(client):
    """Dashboard API"""
    r = client.get('/api/dashboard')
    assert r.status_code == 200


def test_api_news_dates(client):
    """舆情日期列表"""
    r = client.get('/api/news_dates')
    assert r.status_code == 200


def test_api_summary(client):
    """AI 总结 API"""
    r = client.get('/api/summary')
    assert r.status_code == 200


def test_api_quant_status(client):
    """量化引擎状态"""
    r = client.get('/api/quant/status')
    assert r.status_code == 200
    data = r.json()
    assert 'total_reviews' in data


def test_api_inflection(client):
    """拐点检测 API"""
    r = client.get('/api/inflection')
    assert r.status_code == 200


def test_api_alerts(client):
    """预警配置 API"""
    r = client.get('/api/alerts/config')
    assert r.status_code == 200
