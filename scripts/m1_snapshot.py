# -*- coding: utf-8 -*-
"""M1 大盘环境闸门每日快照落库。
计算四指数 weekly(最低低点fib) x daily(末段回吐) 嵌套系数，写入 env_snapshot。
每日收盘后由 cron 触发。algo_version 记录参数版本，供回测复盘。
m1_v5_20261011：确认位切换修复 / 硬闸门只认 pullback 破起点 / 日线两态化 / 决策三段化。"""
import sys, os, sqlite3, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'quant'))
import env_gate as eg
from weekly_gate import weekly_gate
from daily_gate import daily_gate

DB = os.path.join(os.path.dirname(__file__), '..', 'data', 'wave_analysis.db')
INDICES = [('sh000001', '上证指数'), ('sz399001', '深证成指'),
           ('sz399006', '创业板指'), ('sh000688', '科创50')]
# regime 不再写死：由人工锁定浪型自动推导（推动浪向上 = bull）
def _derive_regime(recs):
    w3 = [r for r in recs if r['wave_name'] == '3']
    if not w3:
        return 'bull'
    w3 = w3[0]
    return 'bull' if w3['end_price'] >= w3['start_price'] else 'bear'
ALGO_VER = 'm1_v5_20261011'  # 确认位切换修复 + 硬闸门相位修正 + 日线两态化 + 决策三段化

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
saved = 0
for code, name in INDICES:
    recs = [dict(r) for r in con.execute(
        "SELECT wave_name,start_date,end_date,start_price,end_price,status FROM wave_labels WHERE code=? AND level='weekly' AND confirmed=1 ORDER BY id", (code,))]
    last = con.execute('SELECT trade_date,close FROM index_daily WHERE code=? ORDER BY trade_date DESC LIMIT 1', (code,)).fetchone()
    trade_date = last['trade_date']; cur = last['close']; regime = _derive_regime(recs)
    w3 = [r for r in recs if r['wave_name'] == '3'][0]
    after = con.execute('SELECT high,low,close FROM index_daily WHERE code=? AND trade_date>? ORDER BY trade_date', (code, w3['end_date'])).fetchall()
    ah = [r['high'] for r in after]; al = [r['low'] for r in after]
    ac = [r['close'] for r in after]
    wk = weekly_gate(recs, ah, al, ac, regime)
    kind = 'push' if (wk and wk['phase'] == 'thrust') else 'pull'
    dy = daily_gate(kind, ah, al, ac, 0.04)
    wc = wk['coef'] if wk else 0.0
    dc = dy['coef'] if dy else 0.0
    con.execute('''INSERT OR REPLACE INTO env_snapshot
      (trade_date,code,name,regime,wave,weekly_phase,weekly_ratio,weekly_coef,
       confirm_level,wave_low_at,daily_phase,daily_ratio,daily_coef,index_coef,
       asof_price,algo_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
      (trade_date, code, name, regime, wk['wave'] if wk else None,
       wk['phase'] if wk else None, wk['ratio'] if wk else None, wc,
       wk.get('confirm') if wk else None, wk.get('low_at') if wk else None,
       dy['phase'] if dy else None, dy['ratio'] if dy else None, dc,
       round(wc * dc, 4), cur, ALGO_VER, now))
    saved += 1
con.commit()
print('env_snapshot 写入 %d 条, trade_date=%s, version=%s' % (saved, trade_date, ALGO_VER))
con.close()
