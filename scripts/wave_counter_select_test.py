import sqlite3, math
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

def fib_soft(x, lo, hi, hard_lo=0.0, hard_hi=999):
    if x is None: return 0.0
    if lo-1e-9<=x<=hi+1e-9: return 1.0
    if x<lo: d=(lo-x)/max(lo-hard_lo,1e-9)
    else: d=(x-hi)/max(hard_hi-hi,1e-9)
    return max(0.0,1.0-d)

def select_impulse_up(dates, highs, lows, piv, i_start, t):
    results=[]; n=len(piv)
    for j in range(i_start+1, n):
        if piv[j][2]!='bottom': continue
        p0 = piv[i_start][1]; p2 = piv[j][1]
        if p2 <= p0: continue
        top1s = [(k,piv[k][1]) for k in range(i_start+1,j) if piv[k][2]=='top']
        if not top1s: continue
        k1, p1 = max(top1s, key=lambda x:x[1])
        l1=p1-p0; l2=p1-p2
        if l1<=0 or l2<=0: continue
        r2=l2/l1
        top3s = [(k,piv[k][1]) for k in range(j+1,n) if piv[k][2]=='top']
        if not top3s: continue
        k3, p3 = max(top3s, key=lambda x:x[1])
        l3=p3-p2
        if l3<=0: continue
        bot3s = [(k,piv[k][1]) for k in range(k3+1,n) if piv[k][2]=='bottom']
        complete = len(bot3s)>0
        if complete:
            k4, p4 = min(bot3s, key=lambda x:x[1])
        else:
            run_low = min(lows[piv[k3][0]:t+1])
            k4, p4 = t, run_low
        l4=p3-p4
        if l4<=0: continue
        if p4 < p1: continue
        bot3_idx = k4 if complete else piv[k3][0]
        run_high = max(highs[bot3_idx:t+1])
        p5=run_high; l5=p5-p4
        if l5<=0: continue
        if complete and l3 < min(l1,l5)-1e-9: continue
        s = (fib_soft(r2,0.382,0.786,0.236,1.0)
             + (2.0 if l3/l1>=1.618 else fib_soft(l3/l1,1.0,2.618,0.382,4.236))
             + fib_soft(l4/l3,0.236,0.5,0.146,1.0)
             + fib_soft(l5/l1,0.618,1.618,0.236,2.618))
        d4 = dates[k4] if complete else 'RUNNING'
        results.append({'score':round(s,2),'complete':complete,
            'segs':[dates[piv[i_start][0]]+'('+str(round(p0))+')->'+dates[piv[k1][0]]+'('+str(round(p1))+')',
                   dates[piv[j][0]]+'('+str(round(p2))+')',
                   dates[piv[k3][0]]+'('+str(round(p3))+')',
                   d4+'('+str(round(p4))+')',
                   dates[t]+'('+str(round(p5))+')'],
            'fib':{'w2ret':round(r2,3),'w3w1':round(l3/l1,2),'w4w3':round(l4/l3,3),'w5w1':round(l5/l1,2)},
            'inv':p4})
    return results

for thr in (0.08, 0.10, 0.12):
    piv = zigzag_hl(highs, lows, thr)
    t = len(closes)-1
    print()
    print('########## thr='+str(int(thr*100))+'% pivots='+str(len(piv))+' ##########')
    all_res=[]
    for i in range(len(piv)):
        if piv[i][2]=='bottom':
            all_res.extend(select_impulse_up(dates, highs, lows, piv, i, t))
    all_res.sort(key=lambda x:-x['score'])
    print('impulse candidates:', len(all_res))
    for r in all_res[:6]:
        print('  score='+str(r['score']), 'complete='+str(r['complete']), 'inv='+str(round(r['inv'])))
        print('   ', ' '.join(r['segs']))
        print('    fib='+str(r['fib']))
