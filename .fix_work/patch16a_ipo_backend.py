# -*- coding: utf-8 -*-
"""patch16: 新股评分模块修复（涨幅显示 + 6处逻辑）
1. get_realtime_quote 四级兜底（levistock→ths→tencent→CSV）+ 字段映射对齐
2. score_dim3_chip 首日对比 bug（day_index>0 恒真 → 拿自己当前日当前日）
3. VWAP 手/股单位（else 分支漏 ×100 → 动量分恒 100）
4. 阈值随结果下发（消除前后端两套阈值 + off-by-one）
5. calc_day_index 接入交易日历（跳节假日）
6. 小项：大单集中度 SQL 语义 / 注释对齐
前端（ipo.js）：阈值表同步+off-by-one 修正、D1 三段式配置与公式对齐后端
"""
import pathlib, re, sys

ROOT = pathlib.Path('/opt/stock-review')

REL = 'quant/ipo_score_v2.py'
p = ROOT / REL
s = p.read_text(encoding='utf-8')

def rep(old, new, count=1):
    global s
    n = s.count(old)
    if n != count:
        print('!! expect %d, got %d: %r' % (count, n, old[:70]))
        sys.exit(1)
    s = s.replace(old, new)
    print('ok %r' % old[:55])

# ── 1) get_realtime_quote 重写：四级兜底 ──
NEW_QUOTE = '''def get_realtime_quote(code):
    """获取实时行情（四级兜底：levistock → 同花顺快照 → 腾讯 → 当日CSV）

    返回统一字段：name/price/open/high/low/change_pct/turnover/volume/amount/circ_market/total_market
    """
    # 1) levistock 东方财富
    try:
        import sys as _sys
        if '/opt/levistock' not in _sys.path:
            _sys.path.insert(0, '/opt/levistock')
        import levistock as ls
        result = ls.stocks_em(stock_codes=[code])
        if result is not None and len(result) > 0:
            row = result[0].to_dict() if hasattr(result[0], 'to_dict') else dict(result[0])
            price = float(row.get('price', row.get('latest', 0)) or 0)
            if price > 0:
                return {
                    'name': row.get('stock_name', row.get('name', '')) or '',
                    'price': price,
                    'open': float(row.get('open', 0) or 0),
                    'high': float(row.get('high', 0) or 0),
                    'low': float(row.get('low', 0) or 0),
                    'change_pct': float(row.get('change_pct', row.get('change_percent', 0)) or 0),
                    'turnover': float(row.get('turnover_rate', row.get('turnover', 0)) or 0),
                    'volume': float(row.get('volume', 0) or 0),
                    'amount': float(row.get('amount', 0) or 0),
                    'circ_market': float(row.get('circ_market', 0) or 0),
                    'total_market': float(row.get('total_market', 0) or 0),
                    '_src': 'levistock',
                }
    except Exception as e:
        logger.debug("levistock行情失败 %s: %s" % (code, e))

    # 2) 同花顺快照（注意：turnover 字段实为成交额(元)，volume 为股）
    try:
        import sys as _sys
        _qp = str(BASE_DIR / 'quant')
        if _qp not in _sys.path:
            _sys.path.insert(0, _qp)
        from ths_api import get_snapshot
        mkt = 'SH' if str(code).startswith(('6', '9')) else 'SZ' if str(code).startswith(('0', '3')) else 'BJ'
        snaps = get_snapshot(['%s.%s' % (code, mkt)])
        if snaps:
            sc = snaps[0]
            price = float(sc.get('last_price', 0) or 0)
            if price > 0:
                vol_shares = float(sc.get('volume', 0) or 0)
                turnover = 0
                pred = get_prediction(code)
                fs = float((pred or {}).get('float_shares', 0) or 0) * 1e4  # 万股→股
                if fs > 0 and vol_shares > 0:
                    turnover = round(vol_shares / fs * 100, 2)
                return {
                    'name': '',
                    'price': price,
                    'open': float(sc.get('open_price', 0) or 0),
                    'high': float(sc.get('high_price', 0) or 0),
                    'low': float(sc.get('low_price', 0) or 0),
                    'change_pct': round(float(sc.get('price_change_ratio_pct', 0) or 0), 2),
                    'turnover': turnover,
                    'volume': vol_shares,
                    'amount': float(sc.get('turnover', 0) or 0),
                    'circ_market': 0,
                    'total_market': 0,
                    '_src': 'ths',
                }
    except Exception as e:
        logger.debug("同花顺快照兜底失败 %s: %s" % (code, e))

    # 3) 腾讯全市场
    try:
        from quant.tencent_data import fetch_full_market_tencent
        for row in (fetch_full_market_tencent() or []):
            if str(row.get('code', '')) == str(code):
                return {
                    'name': row.get('name', '') or '',
                    'price': float(row.get('price', 0) or 0),
                    'open': float(row.get('open', 0) or 0),
                    'high': float(row.get('high', 0) or 0),
                    'low': float(row.get('low', 0) or 0),
                    'change_pct': float(row.get('change_pct', 0) or 0),
                    'turnover': 0,
                    'volume': float(row.get('volume', 0) or 0),
                    'amount': float(row.get('amount', 0) or 0),
                    'circ_market': 0,
                    'total_market': 0,
                    '_src': 'tencent',
                }
    except Exception as e:
        logger.debug("腾讯行情兜底失败 %s: %s" % (code, e))

    # 4) 当日CSV（收盘后可用）
    try:
        import csv as _csv
        fp = BASE_DIR / 'data' / 'csv' / ('stock_daily_%s.csv' % datetime.now().strftime('%Y%m%d'))
        if fp.exists():
            with open(fp, encoding='utf-8-sig') as f:
                for r in _csv.DictReader(f):
                    if str(r.get('\\u80a1\\u7968\\u4ee3\\u7801', '')).strip() == str(code):
                        return {
                            'name': r.get('\\u80a1\\u7968\\u540d\\u79f0', '') or '',
                            'price': float(r.get('\\u6700\\u65b0\\u4ef7', 0) or 0),
                            'open': float(r.get('\\u5f00\\u76d8\\u4ef7', 0) or 0),
                            'high': float(r.get('\\u6700\\u9ad8\\u4ef7', 0) or 0),
                            'low': float(r.get('\\u6700\\u4f4e\\u4ef7', 0) or 0),
                            'change_pct': float(r.get('\\u6da8\\u8dcc\\u5e45', 0) or 0),
                            'turnover': float(r.get('\\u6362\\u624b\\u7387', 0) or 0),
                            'volume': 0,
                            'amount': float(r.get('\\u6210\\u4ea4\\u989d', 0) or 0),
                            'circ_market': 0,
                            'total_market': 0,
                            '_src': 'csv',
                        }
    except Exception as e:
        logger.debug("CSV兜底失败 %s: %s" % (code, e))
    return {}

'''
pat = re.compile(r'def get_realtime_quote\(code\):.*?(?=def get_open_turnover_from_minute)', re.S)
s, n = pat.subn(lambda _m: NEW_QUOTE, s)
print('replaced get_realtime_quote x%d' % n)
if n != 1:
    sys.exit(1)

# ── 2) D1 换手衰减：day_index>0 恒真导致首日拿自己当前日 ──
rep('    if day_index > 0:\n        perf_prev = get_daily_performance(code, day_index - 1)',
    '    if day_index > 1:  # 首日(D1)无前日对比（原条件恒真，首日误拿自己当前日当历史）\n        perf_prev = get_daily_performance(code, day_index - 1)')

# ── 3) VWAP 手→股（else 分支漏 ×100，导致动量分恒 100） ──
rep('''        else:
            total_amt = sum(float(p.get('amount', 0) or 0) for p in all_perf_list)
            total_vol = sum(float(p.get('volume', 0) or 0) for p in all_perf_list)
            if total_vol > 0:
                vwap = total_amt / total_vol''',
    '''        else:
            total_amt = sum(float(p.get('amount', 0) or 0) for p in all_perf_list)
            total_vol_shares = sum(float(p.get('volume', 0) or 0) * 100 for p in all_perf_list)  # 手→股
            if total_vol_shares > 0:
                vwap = total_amt / total_vol_shares''')

# ── 5) calc_day_index 接入交易日历（跳节假日） ──
rep('''        trading_days = 0
        current = ld
        while current < today:
            if current.weekday() < 5:  # 周一到周五
                trading_days += 1
            current += timedelta(days=1)''',
    '''        trading_days = 0
        current = ld
        try:
            from utils import is_trading_day as _itd
        except Exception:
            _itd = None
        while current < today:
            _ds = current.strftime('%Y%m%d')
            if _itd(_ds) if _itd else current.weekday() < 5:  # 交易日历口径（跳周末+节假日）
                trading_days += 1
            current += timedelta(days=1)''')

# ── 4) 阈值随结果下发 ──
rep("""        'turnover_timepoints': turnover_tp,
        'prediction_summary': prediction,""",
    """        'turnover_timepoints': turnover_tp,
        'turnover_thresholds': get_thresholds(day_index),
        'prediction_summary': prediction,""")

# ── 6) 小项 ──
rep('        row = conn.execute("SELECT COUNT(*) as cnt FROM ipo_snapshots WHERE code=? ORDER BY id DESC LIMIT 1", (code,)).fetchone()',
    '        row = conn.execute("SELECT 1 FROM ipo_snapshots WHERE code=? LIMIT 1", (code,)).fetchone()')
rep('    # 开盘涨幅合理区间：首日60-120%，后面递减',
    '    # 开盘涨幅合理区间：D1 50-120%，D2 -10~30%，其后 -5~20%')

p.write_text(s, encoding='utf-8')
print('patch16 backend done')
