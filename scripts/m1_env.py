# -*- coding: utf-8 -*-
"""M1 大盘环境闸门 v5（m1_v5_20261011）——人工锁定框架 x 确认位 x 日线企稳，嵌套合成。每日查看。

v5：确认位切换修复（首个已确认反弹高，固定水平）/ 硬闸门只认 pullback 破起点 /
    决策三段化（full/observe/reject）/ 日线层两态化。"""
import sys, sqlite3, os
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

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
index_evals = {}
asof = None
for code, name in INDICES:
    recs = [dict(r) for r in con.execute(
        "SELECT wave_name,start_date,end_date,start_price,end_price,status FROM wave_labels WHERE code=? AND level='weekly' AND confirmed=1 ORDER BY id", (code,))]
    last = con.execute('SELECT trade_date,close FROM index_daily WHERE code=? ORDER BY trade_date DESC LIMIT 1', (code,)).fetchone()
    asof = last['trade_date']; cur = last['close']; regime = _derive_regime(recs)
    w3_end = [r for r in recs if r['wave_name'] == '3'][0]['end_date']
    after = con.execute('SELECT high,low,close FROM index_daily WHERE code=? AND trade_date>? ORDER BY trade_date', (code, w3_end)).fetchall()
    ah = [r['high'] for r in after]; al = [r['low'] for r in after]; ac = [r['close'] for r in after]
    wk = weekly_gate(recs, ah, al, ac, regime)
    # weekly机械状态：thrust则子浪push，否则pull
    kind = 'push' if (wk and wk['phase'] == 'thrust') else 'pull'
    dy = daily_gate(kind, ah, al, ac, 0.04)
    wc = wk['coef'] if wk else 0.0
    dc = dy['coef'] if dy else 0.0
    index_evals[code] = {'weekly': wk, 'daily': dy, 'weekly_coef': wc,
                         'daily_coef': dc, 'index_coef': round(wc * dc, 3),
                         'regime': regime, 'name': name}
con.close()

env = eg.evaluate_env(index_evals)
print('M1 大盘环境闸门 v5  (asof %s)' % asof)
print('=' * 86)
print('环境标签: %s   [决策: %s]' % (env['label'], env.get('decision', '-')))
print('env_coef=%.3f raw=%.3f divergence=%.3f hard_gate=%s' % (
    env['env_coef'], env['raw_coef'], env['divergence'], env['hard_gate']))
print('-' * 86)
for code, name in INDICES:
    e = index_evals[code]; wk = e['weekly']; dy = e['daily']
    print('{: <5} {} index={:.2f}'.format(name, e['regime'], e['index_coef']))
    if wk:
        print('        weekly {: <9} ratio {:6.1f}% coef {:.2f} confirm={} low={}  {}'.format(
            wk['phase'], wk['ratio'] * 100, wk['coef'], wk['confirm'], wk.get('low_at'), wk['zone']))
    if dy:
        rr = dy['ratio']
        rstr = '{:6.1f}%'.format(rr * 100) if rr else '   -- '
        print('        daily  {: <16} {} coef {:.2f}  {}'.format(
            dy['phase'], rstr, dy['coef'], dy['zone']))
print('=' * 86)
