#!/bin/bash
cd /opt/stock-review
echo "=== A1 交易日历抽测 ==="
PYTHONPATH=/opt/stock-review python3.11 - <<'PYEOF'
from utils import is_trading_day, get_prev_trading_day, get_prev_trading_days, is_trade_time_now
print('20261001(国庆) is_trading_day:', is_trading_day('20261001'), '(expect False)')
print('20260930 is_trading_day:', is_trading_day('20260930'), '(expect True)')
print('get_prev_trading_day(20261009):', get_prev_trading_day('20261009'), '(expect 20260930, 跳过国庆)')
print('get_prev_trading_days(20261009, 3):', get_prev_trading_days('20261009', 3), '(expect 30/29/28)')
print('is_trade_time_now():', is_trade_time_now(), '(16:17 收盘后期望 False)')
PYEOF

echo "=== A6 涨停口径抽测 ==="
PYTHONPATH=/opt/stock-review python3.11 - <<'PYEOF'
from utils import is_zt, is_zb, get_limit_threshold
z1 = {'股票代码': '600001', '股票名称': '测试A', '昨收': 10.0, '最新价': 11.0, '最高价': 11.0, '涨跌幅': 10.0}
z2 = {'股票代码': '600001', '股票名称': '测试A', '昨收': 10.0, '最新价': 10.95, '最高价': 11.0, '涨跌幅': 9.5}
st = {'股票代码': '600002', '股票名称': 'ST测试', '昨收': 10.0, '最新价': 10.5, '最高价': 10.5, '涨跌幅': 5.0}
bj = {'股票代码': '830001', '股票名称': '北证测试', '昨收': 10.0, '最新价': 12.9, '最高价': 13.1, '涨跌幅': 12.9}
print('涨停(10.0):', is_zt(z1), '(expect True)')
print('未封板(9.5+盘中触板):', is_zt(z2), '(expect False) / 炸板:', is_zb(z2), '(expect True)')
print('ST涨停(5.0):', is_zt(st), '(expect True) threshold:', get_limit_threshold('600002', 'ST测试'), '(expect 5.0)')
print('北交所触板回落:', is_zb(bj), '(expect True) threshold:', get_limit_threshold('830001'), '(expect 30.0)')
PYEOF

echo "=== A7 vol_ratio 缓冲字段抽测 ==="
PYTHONPATH=/opt/stock-review python3.11 - <<'PYEOF'
from quant.realtime_service import RealtimeService
s = RealtimeService()
print('_amt_buffer 条数:', len(s._amt_buffer), '(daily_sentiment_cache 有效历史天数, 期望>0)')
print('_amt_buffer_date:', repr(s._amt_buffer_date), "(期望 '')")
PYEOF

echo "=== A6 连板与涨停口径一致性 ==="
PYTHONPATH=/opt/stock-review python3.11 - <<'PYEOF'
import json, glob
from lianban import compute_lianban_tiers
from data import get_available_dates, load_review
dates = [d['date'] for d in get_available_dates()]
d = dates[-1]
lb = compute_lianban_tiers(d)
rv = load_review(d) or {}
print(d, 'lianban total_zt:', lb.get('total_zt'), '| review zt_count:', rv.get('zt_count'),
      '| highest:', lb.get('highest_board'))
PYEOF

echo "=== nginx /static/ 缓存头 ==="
curl -sI http://127.0.0.1:8501/static/js/config.js >/dev/null
curl -sI https://127.0.0.1/static/js/config.js -k -H 'Host: yoyomeat.cn' | grep -i "cache-control\|HTTP/"

echo "=== journal 空间回收 ==="
journalctl --disk-usage
journalctl --vacuum-size=200M >/dev/null 2>&1
journalctl --disk-usage

echo "=== 最终 pytest ==="
PYTHONPATH=/opt/stock-review timeout 300 python3 -m pytest tests -q 2>&1 | tail -2
