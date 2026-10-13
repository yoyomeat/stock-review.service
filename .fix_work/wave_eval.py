# -*- coding: utf-8 -*-
"""模块一（market_wave_engine）波浪自动判定的历史实证：
walk-forward 截断历史 → 记录当时判定 → 对照后续实际收益，输出命中率/单调性/锚点漂移。
"""
import sys, sqlite3
sys.path.insert(0, '/opt/stock-review')
from quant import market_wave_engine as mwe

FULL = {}
conn = sqlite3.connect(mwe.DB_PATH)
for code in mwe.INDICES:
    rows = conn.execute(
        "SELECT trade_date, close FROM index_daily WHERE code=? AND trade_date>='20240101' ORDER BY trade_date",
        (code,)).fetchall()
    FULL[code] = ([r[0] for r in rows], [float(r[1]) for r in rows])
lbl = conn.execute("SELECT code, wave_name, start_date, start_price, status FROM wave_labels WHERE level='weekly'").fetchall()
conn.close()
print('wave_labels 周线标注:', lbl)
for code, (d, c) in FULL.items():
    print('%s: %d bars, %s ~ %s' % (code, len(d), d[0] if d else '-', d[-1] if d else '-'))

_TRUNC = {}
_orig_load = mwe.load_daily
def _load_trunc(conn, code, start="20240101"):
    return _TRUNC[code]
mwe.load_daily = _load_trunc

def classify(r):
    p = r.get('path', '')
    if '路径B' in p:
        return 'B'
    if '主升' in p:
        return 'A_main'
    if '子1浪' in p:
        return 'A_w1'
    return 'A_w2'

recs = []
anchors = {c: [] for c in FULL}
for code, (dates, closes) in FULL.items():
    n = len(dates)
    locked = code == 'sh000001'  # 有用户锁定标注，walk-forward 会被污染 → 单独标记
    for cut in range(250, n - 1, 3):
        _TRUNC[code] = (dates[:cut], closes[:cut])
        try:
            r = mwe.analyze_one(None, code, dict(mwe.INDICES[code]))
        except Exception:
            continue
        if r.get('error') or not r.get('path'):
            continue
        base = closes[cut - 1]
        fw = {}
        for k, off in (('f5', 5), ('f10', 10), ('f20', 20)):
            j = cut - 1 + off
            fw[k] = (closes[j] / base - 1) * 100 if j < n else None
        anchors[code].append((cut, r.get('wave5_start')))
        recs.append({
            'code': code, 'locked': locked, 'cut': cut,
            'cat': classify(r), 'prob': r.get('prob'),
            'retrace': r.get('retrace'), 'zone': r.get('fib_zone', ''),
            'action': r.get('action', ''),
            **fw,
        })
mwe.load_daily = _orig_load

auto = [x for x in recs if not x['locked']]

def agg(rows, keyfn, title):
    print('\n== %s ==' % title)
    buckets = {}
    for x in rows:
        buckets.setdefault(keyfn(x), []).append(x)
    for k in sorted(buckets, key=lambda z: str(z)):
        b = buckets[k]
        f20 = [x['f20'] for x in b if x['f20'] is not None]
        f5 = [x['f5'] for x in b if x['f5'] is not None]
        if not f20:
            continue
        pos = sum(1 for v in f20 if v > 0) / len(f20) * 100
        print('%-28s n=%-4d f5均值%+.2f%% f20均值%+.2f%% f20中位%+.2f%% 正收益率%+.0f%%'
              % (str(k), len(b), sum(f5) / len(f5), sum(f20) / len(f20),
                 sorted(f20)[len(f20) // 2], pos))

agg(auto, lambda x: x['cat'], '按判定状态（自动锚定三指数）')
agg(auto, lambda x: x['prob'], '按 prob 数值')
agg(auto, lambda x: (x['prob'] // 5) * 5, '按 prob 分桶(5档)')
agg([x for x in auto if x['zone']], lambda x: x['zone'], '按回撤分区（fib_zone）')
agg(auto, lambda x: '绝对买点区' if '绝对买点区' in x['action'] else x['action'], '按 action 文案')
agg([x for x in recs if x['locked']], lambda x: x['cat'], '（参考）上证=用户锁定框架')

print('\n== 锚点漂移（wave5_start 随新数据的变化） ==')
for code, arr in anchors.items():
    prices = [p for _, p in arr if p]
    uniq = sorted(set(prices))
    changes = sum(1 for i in range(1, len(prices)) if prices[i] != prices[i - 1])
    print('%s: 取样%d次 | 不同锚点值%d个 | 相邻取样漂移%d次 | 锚点值: %s'
          % (code, len(prices), len(uniq), changes, uniq[-5:]))

print('\n== 警示质量：判定时状态 vs 未来20日下跌 ==')
for cat in ('A_main', 'A_w2', 'A_w1', 'B'):
    b = [x for x in auto if x['cat'] == cat and x['f20'] is not None]
    if not b:
        continue
    dn = sum(1 for x in b if x['f20'] < -3) / len(b) * 100
    print('%-8s n=%-4d 未来20日跌幅超3%%的概率: %.0f%%' % (cat, len(b), dn))
