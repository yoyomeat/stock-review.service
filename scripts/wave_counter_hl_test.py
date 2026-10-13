"""方向A v2：用日线 high/low 跑 zigzag（波浪拐点是极值不是收盘），阈值扫描。
金标准：2635.09(20240205底) 3674.4(20241008顶) 3040.69(20250407底) 4258.86(20260514顶) 3741.11(20260720底)
"""
import sqlite3
con = sqlite3.connect('/opt/stock-review/data/wave_analysis.db')
rows = con.execute("SELECT trade_date, high, low, close FROM index_daily WHERE code='sh000001' AND trade_date>='20230101' ORDER BY trade_date").fetchall()
con.close()
dates=[r[0] for r in rows]; highs=[r[1] for r in rows]; lows=[r[2] for r in rows]; closes=[r[3] for r in rows]

def zigzag_hl(highs, lows, thr):
    """标准zigzag：向上追踪用high更新顶，向下追踪用low更新底，反转确认才输出。"""
    piv=[]; n=len(highs)
    direction=0; ext_i=0; ext_price=highs[0]
    for i in range(1,n):
        if direction==0:
            if highs[i] > ext_price*(1+thr):
                piv.append((ext_i, lows[ext_i], 'bottom', i))  # 起点是底
                ext_i=i; ext_price=highs[i]; direction=1
            elif lows[i] < ext_price*(1-thr):
                piv.append((ext_i, highs[ext_i], 'top', i))
                ext_i=i; ext_price=lows[i]; direction=-1
        elif direction==1:  # 上升中
            if highs[i] > ext_price:
                ext_price=highs[i]; ext_i=i
            elif lows[i] < ext_price*(1-thr):
                piv.append((ext_i, highs[ext_i], 'top', i))
                ext_i=i; ext_price=lows[i]; direction=-1
        else:  # 下降中
            if lows[i] < ext_price:
                ext_price=lows[i]; ext_i=i
            elif highs[i] > ext_price*(1+thr):
                piv.append((ext_i, lows[ext_i], 'bottom', i))
                ext_i=i; ext_price=highs[i]; direction=1
    return piv

GOLD=[(2635.09,'20240205','bottom'),(3674.4,'20241008','top'),(3040.69,'20250407','bottom'),(4258.86,'20260514','top'),(3741.11,'20260720','bottom')]

for thr in (0.08, 0.10, 0.12, 0.13, 0.15):
    piv = zigzag_hl(highs, lows, thr)
    print(f'\n########## HL-zigzag thr={thr*100:.0f}%  摆点={len(piv)} ##########')
    hit=[False]*5
    for idx, price, kind, conf in piv:
        mark=''
        for j,(gp,gd,gk) in enumerate(GOLD):
            if kind==gk and abs(price-gp)/gp<0.03:
                mark=f'  <<金标准{j+1} {gd} {gp}'; hit[j]=True
        print(f'  {dates[idx]} {kind:6s} {price:8.2f} (确认{dates[conf]}){mark}')
    print(f'  金标准命中: {sum(hit)}/5  {"全部命中!" if all(hit) else ""}')
