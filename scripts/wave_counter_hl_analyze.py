"""用HL-zigzag摆点喂给 wave_counter.analyze，看能否拼出金标准5浪。"""
import sys, sqlite3
sys.path.insert(0, '/opt/stock-review/quant')
from wave_counter import _impulse, _abc, Hyp

con = sqlite3.connect('/opt/stock-review/data/wave_analysis.db')
rows = con.execute("SELECT trade_date, high, low, close FROM index_daily WHERE code='sh000001' AND trade_date>='20230101' ORDER BY trade_date").fetchall()
con.close()
dates=[r[0] for r in rows]; highs=[r[1] for r in rows]; lows=[r[2] for r in rows]; closes=[r[3] for r in rows]

def zigzag_hl(highs, lows, thr):
    piv=[]; n=len(highs); direction=0; ext_i=0; ext_price=highs[0]
    for i in range(1,n):
        if direction==0:
            if highs[i]>ext_price*(1+thr):
                piv.append((ext_i, lows[ext_i],'bottom',i)); ext_i=i; ext_price=highs[i]; direction=1
            elif lows[i]<ext_price*(1-thr):
                piv.append((ext_i, highs[ext_i],'top',i)); ext_i=i; ext_price=lows[i]; direction=-1
        elif direction==1:
            if highs[i]>ext_price: ext_price=highs[i]; ext_i=i
            elif lows[i]<ext_price*(1-thr):
                piv.append((ext_i, highs[ext_i],'top',i)); ext_i=i; ext_price=lows[i]; direction=-1
        else:
            if lows[i]<ext_price: ext_price=lows[i]; ext_i=i
            elif highs[i]>ext_price*(1+thr):
                piv.append((ext_i, lows[ext_i],'bottom',i)); ext_i=i; ext_price=highs[i]; direction=1
    return piv

for thr in (0.08, 0.10, 0.12):
    piv = zigzag_hl(highs, lows, thr)
    # 把piv转成 (idx, price, kind, conf) 喂给_impulse
    print(f'\n########## thr={thr*100:.0f}% 摆点{len(piv)}个 ##########')
    t = len(closes)-1
    hyps=[]
    for i in range(len(piv)):
        for up in (True, False):
            r = _impulse(dates, closes, piv, i, up, t)
            if r:
                h, inv = r; h.invalidation=inv; hyps.append(h)
    hyps.sort(key=lambda h:-h.score)
    print(f'impulse假设数: {len(hyps)}')
    for h in hyps[:8]:
        seg=' '.join(f'{w[0]}:{dates[w[1]]}({w[2]:.0f}->{w[4]:.0f})' for w in h.waves)
        print(f'  score={h.score:.2f} kind={h.kind}')
        print(f'    {seg}')
        print(f'    fib={h.fib} inv={h.invalidation:.0f}')
