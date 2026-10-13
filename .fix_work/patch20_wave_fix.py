# -*- coding: utf-8 -*-
"""patch20: 修复 patch18 引入的遗漏 —— w2 分支未赋 path（导致路径文本空、A_w2 不进标定、合成计数错）+ 文案空格"""
import pathlib, sys

ROOT = pathlib.Path('/opt/stock-review')
REL = 'quant/market_wave_engine.py'
p = ROOT / REL
s = p.read_text(encoding='utf-8')

def rep(old, new):
    global s
    n = s.count(old)
    if n != 1:
        print('!! expect 1, got %d: %r' % (n, old[:70]))
        sys.exit(1)
    s = s.replace(old, new)
    print('ok %r' % old[:55])

rep('''            if time_ratio and time_ratio > 1.5:
                prob = max(50, prob - 8)
                subwave_desc += "；回调用时已达上涨时段%.2f倍，结构存疑" % time_ratio
            action = "回调区分批"''',
    '''            if time_ratio and time_ratio > 1.5:
                prob = max(50, prob - 8)
                subwave_desc += "；回调用时已达上涨时段%.2f倍，结构存疑" % time_ratio
            if fib_key and cur_price >= fib_key:
                path = "路径A：大五浪上升（子2浪回调中，站上斐波那契关键位）"
            elif fib_key and cur_price < fib_key:
                path = "路径A：大五浪上升（子2浪回调中，关键位下方）"
            else:
                path = "路径A：大五浪上升（子2浪回调中）"
            action = "回调区分批"''')

rep('''        extra = ""
        if res.get("time_ratio") and res["time_ratio"] > 1.5:
            extra = "注意：回调用时已达上涨时段%.2f倍，结构存疑。" % res["time_ratio"]''',
    '''        extra = ""
        if res.get("time_ratio") and res["time_ratio"] > 1.5:
            extra = " 注意：回调用时已达上涨时段%.2f倍，结构存疑。" % res["time_ratio"]''')

p.write_text(s, encoding='utf-8')
print('patch20 done')
