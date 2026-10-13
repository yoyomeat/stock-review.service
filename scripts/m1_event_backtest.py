"""M1 正确口径回测——所有历史bottom（含失败案例），按大趋势状态×fib回撤分段。

PIT处理：bottom在'反弹达thr'那天才确认，从确认日算后续收益。
大趋势状态：大尺度zigzag最近确认摆点的方向。
"""
import sys, sqlite3
sys.path.insert(0, '/opt/stock-review/quant')
from wave_counter import pivots_hl

con = sqlite3.connect('/opt/stock-review/data/wave_analysis.db')
INDICES = [('sh000001','上证'), ('sz399001','深成指'),
           ('sz399006','创业板'), ('sh000688','科创50')]

MID=0.08; BIG=0.15


def build_pivots_with_confirm(highs, lows, dates, thr):
    # pivots_hl 已返回 (bar, price, kind, confirm_bar)，PIT无未来函数
    piv = pivots_hl(highs, lows, thr)
    out=[]
    for bar, price, typ, cb in piv:
        out.append({'bar':bar,'date':dates[bar],'price':price,'type':typ,
                    'confirm':cb,'confirm_date':dates[cb]})
    return out


events=[]
for code, name in INDICES:
    rows = con.execute('SELECT trade_date,high,low,close FROM index_daily WHERE code=? ORDER BY 1',(code,)).fetchall()
    dates=[r[0] for r in rows]; highs=[r[1] for r in rows]; lows=[r[2] for r in rows]; closes=[r[3] for r in rows]

    mid = build_pivots_with_confirm(highs, lows, dates, MID)
    big = build_pivots_with_confirm(highs, lows, dates, BIG)

    # 对每个中尺度bottom
    for k, p in enumerate(mid):
        if p['type']!='bottom' or p['confirm'] is None: continue
        # 找前一段上涨：之前最近的mid bottom -> 之前最近的mid top
        prev_tops=[q for q in mid[:k] if q['type']=='top']
        prev_bots=[q for q in mid[:k] if q['type']=='bottom']
        if not prev_tops or not prev_bots: continue
        top = prev_tops[-1]
        # 上涨起点 = 这个top之前最近的bottom
        bots_before_top=[q for q in prev_bots if q['bar']<top['bar']]
        if not bots_before_top: continue
        start = bots_before_top[-1]
        up_leg = top['price']-start['price']
        if up_leg<=0: continue
        fib = (top['price']-p['price'])/up_leg  # 回撤比例

        # 大趋势状态：确认日时，大尺度最近已确认摆点
        cb = p['confirm']
        big_confirmed=[q for q in big if q['confirm'] is not None and q['confirm']<=cb]
        if not big_confirmed: continue
        last_big = big_confirmed[-1]
        big_trend = '大趋势向上' if last_big['type']=='bottom' else '大趋势向下'

        # 后续收益（从确认bar、确认时价格水平算）
        entry_price = p['price']*(1+MID)  # 确认时约反弹8%
        def fwd(h):
            if cb+h < len(closes):
                return (closes[cb+h]/entry_price-1)*100
            return None
        events.append({
            'index':name,'date':p['date'],'confirm_date':dates[cb],
            'fib':fib,'big_trend':big_trend,
            'r5':fwd(5),'r10':fwd(10),'r20':fwd(20),'r60':fwd(60),
        })

con.close()
print(f'总bottom事件（含失败）: {len(events)}')


def seg_of(fib):
    if fib<0.382: return '<38.2%浅'
    if fib<0.50: return '38.2-50%'
    if fib<0.618: return '50-61.8%标准'
    if fib<0.786: return '61.8-78.6%'
    return '>78.6%过深'

SEGS=['<38.2%浅','38.2-50%','50-61.8%标准','61.8-78.6%','>78.6%过深']

for trend in ('大趋势向上','大趋势向下'):
    sub=[e for e in events if e['big_trend']==trend]
    print()
    print('='*78)
    print(f'  {trend}  (事件 n={len(sub)})')
    print('='*78)
    print(f"{'fib回撤分段':<16}{'n':>3}  {'r5':>7}  {'r10':>7}  {'r20':>7}  {'r60':>7}  {'r20胜率':>7}  {'r20中位数':>8}")
    for seg in SEGS:
        items=[e for e in sub if seg_of(e['fib'])==seg]
        if not items:
            print(f'{seg:<16}{0:>3}')
            continue
        n=len(items)
        def stats(h):
            v=sorted(e['r'+str(h)] for e in items if e['r'+str(h)] is not None)
            if not v: return None,None,None
            avg=sum(v)/len(v); med=v[len(v)//2]; win=sum(1 for x in v if x>0)/len(v)*100
            return avg,med,win
        a5,_,_=stats(5); a10,_,_=stats(10); a20,m20,w20=stats(20); a60,_,_=stats(60)
        f=lambda v: f'{v:+.1f}%' if v is not None else '  n/a'
        print(f'{seg:<16}{n:>3}  {f(a5):>7}  {f(a10):>7}  {f(a20):>7}  {f(a60):>7}  {w20:>6.0f}%  {f(m20):>8}')

# 失败案例明细（大趋势向下的bottom）
print()
print('大趋势向下的bottom（下跌中继，应回避）明细:')
for e in sorted([x for x in events if x['big_trend']=='大趋势向下'],key=lambda x:x['confirm_date']):
    r20=e['r20']; r20s=f'{r20:+.1f}%' if r20 is not None else 'n/a'
    print(f"  {e['index']:<5} 确认{e['confirm_date']} fib={e['fib']*100:5.1f}% r20={r20s}")
