#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 tdxrs (Rust通达信后端) 拉取全市场流通股本，缓存到磁盘。

数据源：上证云通达信服务器（get_finance_info），不依赖东财/腾讯 HTTP。
单位：万股（与 quant/intraday_sentiment.py 的 float_shares 口径一致）。
建议：交易日盘前由 cron 调用一次；当天已有缓存默认跳过（--force 强制刷新）。
"""
import sys, time, json, datetime, argparse, os

BASE_DIR = '/opt/stock-review'
sys.path.insert(0, BASE_DIR)
from tdxrs_fetch import TdxHqClient, TDX_SERVERS, MARKET_SH, MARKET_SZ

CACHE_FILE = os.path.join(BASE_DIR, 'data', 'float_shares_rs.json')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    today = datetime.datetime.now().strftime('%Y%m%d')

    # 当天缓存已存在则跳过
    if not args.force and os.path.exists(CACHE_FILE):
        try:
            c = json.load(open(CACHE_FILE))
            if c.get('date') == today and len(c.get('data', {})) > 3000:
                print('当天缓存已存在: %d 只，跳过' % len(c['data']))
                return 0
        except Exception:
            pass

    client = TdxHqClient()
    ok = False
    for h, p in TDX_SERVERS:
        try:
            if client.connect(h, p):
                ok = True
                print('connected', h)
                break
        except Exception:
            pass
    if not ok:
        print('connect fail')
        return 1

    try:
        stocks = []
        for mkt in [MARKET_SH, MARKET_SZ]:
            start = 0
            while True:
                r = client.get_security_list(mkt, start)
                if not r:
                    break
                for s in r:
                    c = s.get('code', '')
                    if c and len(c) == 6 and c[0] in ('0', '3', '6'):
                        stocks.append((mkt, c))
                if len(r) < 1000:
                    break
                start += len(r)
        print('股票数:', len(stocks))

        t = time.time()
        fs = {}
        for i, (mkt, c) in enumerate(stocks):
            try:
                info = client.get_finance_info(mkt, c)
                if info and info.get('liutongguben', 0) > 0:
                    fs[c] = info['liutongguben']
            except Exception:
                pass
            if (i + 1) % 1000 == 0:
                print('  %d/%d 有效%d 用时%.0fs' % (i + 1, len(stocks), len(fs), time.time() - t))

        print('完成: %d/%d 有效, 用时%.0fs' % (len(fs), len(stocks), time.time() - t))
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        tmp = CACHE_FILE + '.tmp'
        json.dump({'date': today, 'data': fs}, open(tmp, 'w'))
        os.replace(tmp, CACHE_FILE)
        print('缓存已写:', CACHE_FILE)
        return 0
    finally:
        try:
            client.disconnect()
        except Exception:
            pass


if __name__ == '__main__':
    sys.exit(main())
