#!/usr/bin/env python3
"""补跑历史日线数据 — 使用东方财富 push2his 接口"""
import requests
import csv
import os
import sys
import time

CSV_DIR = '/opt/stock-review/data/csv'
HIS_URL = "https://push2his.eastmoney.com/api/qt/clist/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

CSV_COLUMNS = [
    '交易日期', '股票代码', '股票名称', '最新价', '涨跌幅', '涨跌额',
    '开盘价', '最高价', '最低价', '昨收价', '成交量手', '成交额',
    '振幅', '量比', '换手率', '市盈率动态', '市净率', '总市值', '流动市值', '所属板块',
]

def fetch_historical(date_str):
    """获取指定日期全量A股行情"""
    all_data = []
    page = 1
    total = None
    max_retries = 3
    
    while True:
        params = {
            "pn": str(page), "pz": "100", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23",
            "date": date_str,
        }
        
        for retry in range(max_retries):
            try:
                resp = requests.get(HIS_URL, params=params, headers=HEADERS, timeout=30)
                data = resp.json()
                if data.get("rc") != 0:
                    print(f"  API返回异常 rc={data.get('rc')}")
                    break
                body = data.get("data", {})
                if total is None:
                    total = body.get("total", 0)
                    print(f"  总计 {total} 只股票，每页100条，需{(total+99)//100}页")
                diff = body.get("diff", [])
                if not diff:
                    break
                all_data.extend(diff)
                break
            except Exception as e:
                wait = 5 * (retry + 1)
                print(f"  第{page}页第{retry+1}次失败，等{wait}s重试: {e}")
                time.sleep(wait)
        else:
            print(f"  第{page}页失败，跳过")
            break
            
        if not diff:
            break
        if total and len(all_data) >= total:
            break
        page += 1
        time.sleep(1.5)
        
        if page % 10 == 0:
            print(f"  已获取 {len(all_data)}/{total} 只...")
    
    return all_data

def main():
    dates = sys.argv[1:] if len(sys.argv) > 1 else ['20260618', '20260622']
    
    for date_str in dates:
        csv_path = os.path.join(CSV_DIR, f'stock_daily_{date_str}.csv')
        if os.path.exists(csv_path) and os.path.getsize(csv_path) > 100000:
            print(f'{date_str}: 已存在 ({os.path.getsize(csv_path)} bytes)，跳过')
            continue
        
        print(f'\n采集 {date_str} 全量A股日线数据...')
        raw_data = fetch_historical(date_str)
        print(f'  获取 {len(raw_data)} 只股票')
        
        if not raw_data:
            print(f'  失败: 无数据')
            continue
        
        os.makedirs(CSV_DIR, exist_ok=True)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(CSV_COLUMNS)
            for d in raw_data:
                code = str(d.get("f12", ""))
                if not code:
                    continue
                writer.writerow([
                    date_str, code, str(d.get("f14", "")),
                    d.get("f2", ""), d.get("f3", ""), d.get("f4", ""),
                    d.get("f17", ""), d.get("f15", ""), d.get("f16", ""),
                    d.get("f18", ""), d.get("f5", ""), d.get("f6", ""),
                    d.get("f7", ""), d.get("f10", ""), d.get("f8", ""),
                    d.get("f9", ""), d.get("f23", ""), d.get("f20", ""),
                    d.get("f21", ""), '',
                ])
        
        size_kb = os.path.getsize(csv_path) / 1024
        print(f'  完成: {csv_path} ({len(raw_data)} 行, {size_kb:.0f}KB)')

if __name__ == '__main__':
    main()
